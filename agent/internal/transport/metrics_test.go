package transport_test

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/transport"
)

// newDiscardLogger returns a *slog.Logger that discards all output.
func newDiscardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// newCtxWithTimeout returns a context that is cancelled after the given
// duration and a cancel function that should be deferred by the caller.
func newCtxWithTimeout(t *testing.T, d time.Duration) (context.Context, context.CancelFunc) {
	t.Helper()
	return context.WithTimeout(context.Background(), d)
}

// ── Unit tests for Metrics ────────────────────────────────────────────────────

// TestNewMetrics verifies that NewMetrics returns a zero-initialised struct.
func TestNewMetrics(t *testing.T) {
	m := transport.NewMetrics()
	if m == nil {
		t.Fatal("NewMetrics returned nil")
	}

	// All counters and the gauge must start at zero.
	assertCounter(t, "ConnectionAttempts", m.ConnectionAttempts.Load(), 0)
	assertCounter(t, "ConnectionErrors", m.ConnectionErrors.Load(), 0)
	assertCounter(t, "ReconnectAttempts", m.ReconnectAttempts.Load(), 0)
	assertCounter(t, "AgentRegistrations", m.AgentRegistrations.Load(), 0)
	assertCounter(t, "RegistrationErrors", m.RegistrationErrors.Load(), 0)
	assertCounter(t, "AlertsSent", m.AlertsSent.Load(), 0)
	assertCounter(t, "StreamSendErrors", m.StreamSendErrors.Load(), 0)
	assertCounter(t, "StreamRecvErrors", m.StreamRecvErrors.Load(), 0)
	assertCounter(t, "Connected", m.Connected.Load(), 0)
}

// TestMetricsHandler_PrometheusFormat verifies that Handler writes
// well-formed Prometheus text exposition format output.
func TestMetricsHandler_PrometheusFormat(t *testing.T) {
	m := transport.NewMetrics()
	// Set some non-zero values so we can assert they appear in the output.
	m.ConnectionAttempts.Add(3)
	m.AlertsSent.Add(7)
	m.Connected.Store(1)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	m.Handler().ServeHTTP(rec, req)

	resp := rec.Result()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("handler returned status %d; want 200", resp.StatusCode)
	}

	ct := resp.Header.Get("Content-Type")
	if !strings.HasPrefix(ct, "text/plain") {
		t.Errorf("Content-Type = %q; want text/plain prefix", ct)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	output := string(body)

	// Check that every required metric family is present with correct
	// # HELP, # TYPE, and sample lines.
	expectedMetrics := []struct {
		name     string
		kind     string
		contains string
	}{
		{"transport_connection_attempts_total", "counter", "transport_connection_attempts_total 3"},
		{"transport_connection_errors_total", "counter", "transport_connection_errors_total 0"},
		{"transport_reconnect_attempts_total", "counter", "transport_reconnect_attempts_total 0"},
		{"transport_agent_registrations_total", "counter", "transport_agent_registrations_total 0"},
		{"transport_registration_errors_total", "counter", "transport_registration_errors_total 0"},
		{"transport_alerts_sent_total", "counter", "transport_alerts_sent_total 7"},
		{"transport_stream_send_errors_total", "counter", "transport_stream_send_errors_total 0"},
		{"transport_stream_recv_errors_total", "counter", "transport_stream_recv_errors_total 0"},
		{"transport_connected", "gauge", "transport_connected 1"},
	}

	for _, em := range expectedMetrics {
		helpLine := "# HELP " + em.name
		typeLine := "# TYPE " + em.name + " " + em.kind
		if !strings.Contains(output, helpLine) {
			t.Errorf("missing HELP line for %s", em.name)
		}
		if !strings.Contains(output, typeLine) {
			t.Errorf("missing TYPE line for %s: %s", em.name, typeLine)
		}
		if !strings.Contains(output, em.contains) {
			t.Errorf("missing sample line %q in output:\n%s", em.contains, output)
		}
	}
}

// TestMetricsHandler_ZeroValues verifies the handler works correctly when all
// metrics are at their initial zero values.
func TestMetricsHandler_ZeroValues(t *testing.T) {
	m := transport.NewMetrics()

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	m.Handler().ServeHTTP(rec, req)

	body, _ := io.ReadAll(rec.Result().Body)
	output := string(body)

	// Zero-value samples must still appear (Prometheus requires them).
	if !strings.Contains(output, "transport_connection_attempts_total 0") {
		t.Errorf("zero-value counter not present in output:\n%s", output)
	}
	if !strings.Contains(output, "transport_connected 0") {
		t.Errorf("zero-value gauge not present in output:\n%s", output)
	}
}

// TestWithMetrics_CountersIncrementOnHappyPath verifies that using [WithMetrics]
// with a real stub server causes the expected counters to be incremented.
func TestWithMetrics_CountersIncrementOnHappyPath(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{}
	addr := startStubServer(t, pki, svc)

	m := transport.NewMetrics()
	cfg := makeAgentConfig(addr, pki)
	logger := newDiscardLogger()
	client := transport.New(cfg, logger, transport.WithMetrics(m))

	svc.expectAlerts(2)
	alertCh := make(chan transport.Alert, 4)
	alertCh <- transport.Alert{AlertID: "m-001", TripwireType: "FILE", RuleName: "r1", Severity: "CRITICAL"}
	alertCh <- transport.Alert{AlertID: "m-002", TripwireType: "NETWORK", RuleName: "r2", Severity: "WARN"}

	ctx, cancel := newCtxWithTimeout(t, 10*time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() { done <- client.Run(ctx, alertCh) }()

	svc.waitAlerts(t, 5*time.Second)
	close(alertCh)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return within 5 s")
	}

	// Connection attempt and registration must each have been made exactly once.
	assertCounter(t, "ConnectionAttempts", m.ConnectionAttempts.Load(), 1)
	assertCounter(t, "AgentRegistrations", m.AgentRegistrations.Load(), 1)
	assertCounter(t, "ConnectionErrors", m.ConnectionErrors.Load(), 0)
	assertCounter(t, "RegistrationErrors", m.RegistrationErrors.Load(), 0)

	// Both alerts must have been counted as sent.
	assertCounter(t, "AlertsSent", m.AlertsSent.Load(), 2)

	// No stream errors on a happy path.
	assertCounter(t, "StreamSendErrors", m.StreamSendErrors.Load(), 0)
	assertCounter(t, "StreamRecvErrors", m.StreamRecvErrors.Load(), 0)

	// After a clean shutdown the connection gauge must be 0.
	assertCounter(t, "Connected", m.Connected.Load(), 0)
}

// TestWithMetrics_ReconnectCountedOnFailure verifies that each reconnect attempt
// increments [Metrics.ReconnectAttempts] and that a registration error is
// also tracked.
func TestWithMetrics_ReconnectCountedOnFailure(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{rejectRegister: true}
	addr := startStubServer(t, pki, svc)

	m := transport.NewMetrics()
	cfg := makeAgentConfig(addr, pki)
	cfg.Dashboard.ReconnectDelay = 20 * time.Millisecond
	cfg.Dashboard.ReconnectMaxDelay = 80 * time.Millisecond

	logger := newDiscardLogger()
	client := transport.New(cfg, logger, transport.WithMetrics(m))
	alertCh := make(chan transport.Alert)

	ctx, cancel := newCtxWithTimeout(t, 5*time.Second)

	done := make(chan error, 1)
	go func() { done <- client.Run(ctx, alertCh) }()

	// Allow a few reconnect cycles, then cancel.
	time.Sleep(300 * time.Millisecond)
	cancel()

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Run did not return within 3 s after cancellation")
	}

	// At least one registration attempt and one registration error must have
	// been recorded, and at least one reconnect attempt.
	if m.AgentRegistrations.Load() < 1 {
		t.Errorf("AgentRegistrations = %d; want >= 1", m.AgentRegistrations.Load())
	}
	if m.RegistrationErrors.Load() < 1 {
		t.Errorf("RegistrationErrors = %d; want >= 1", m.RegistrationErrors.Load())
	}
	if m.ReconnectAttempts.Load() < 1 {
		t.Errorf("ReconnectAttempts = %d; want >= 1", m.ReconnectAttempts.Load())
	}
}

// TestWithoutMetrics_NoPanic verifies that a Client created without
// [WithMetrics] runs correctly without panicking (nil metrics are a no-op).
func TestWithoutMetrics_NoPanic(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{}
	addr := startStubServer(t, pki, svc)

	cfg := makeAgentConfig(addr, pki)
	logger := newDiscardLogger()
	// Deliberately do NOT pass WithMetrics.
	client := transport.New(cfg, logger)

	svc.expectAlerts(1)
	alertCh := make(chan transport.Alert, 2)
	alertCh <- transport.Alert{AlertID: "no-metrics-001", TripwireType: "FILE", RuleName: "r1", Severity: "WARN"}

	ctx, cancel := newCtxWithTimeout(t, 10*time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() { done <- client.Run(ctx, alertCh) }()

	svc.waitAlerts(t, 5*time.Second)
	close(alertCh)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run without metrics: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return within 5 s")
	}
}

// ── helpers ───────────────────────────────────────────────────────────────────

func assertCounter(t *testing.T, name string, got, want int64) {
	t.Helper()
	if got != want {
		t.Errorf("metric %s = %d; want %d", name, got, want)
	}
}
