package agent_test

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// --------------------------------------------------------------------------
// Test doubles
// --------------------------------------------------------------------------

// fakeWatcher is a simple in-memory Watcher implementation for tests.
type fakeWatcher struct {
	startErr   error
	events     chan agent.AlertEvent
	stopCalled bool
}

func newFakeWatcher() *fakeWatcher {
	return &fakeWatcher{events: make(chan agent.AlertEvent, 8)}
}

func (f *fakeWatcher) Start(_ context.Context) error {
	if f.startErr != nil {
		return f.startErr
	}
	return nil
}
func (f *fakeWatcher) Stop()                       { f.stopCalled = true; close(f.events) }
func (f *fakeWatcher) Events() <-chan agent.AlertEvent { return f.events }

// fakeQueue records enqueued events and tracks depth.
type fakeQueue struct {
	enqueued []agent.AlertEvent
	closeErr error
}

func (q *fakeQueue) Enqueue(_ context.Context, evt agent.AlertEvent) error {
	q.enqueued = append(q.enqueued, evt)
	return nil
}
func (q *fakeQueue) Depth() int     { return len(q.enqueued) }
func (q *fakeQueue) Close() error   { return q.closeErr }

// fakeTransport records sent events.
type fakeTransport struct {
	startErr error
	sent     []agent.AlertEvent
	stopped  bool
}

func (t *fakeTransport) Start(_ context.Context) error { return t.startErr }
func (t *fakeTransport) Send(_ context.Context, evt agent.AlertEvent) error {
	t.sent = append(t.sent, evt)
	return nil
}
func (t *fakeTransport) Stop() { t.stopped = true }

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

func minimalConfig() *config.Config {
	return &config.Config{
		DashboardAddr: "dashboard.example.com:4443",
		TLS: config.TLSConfig{
			CertPath: "/etc/tripwire/agent.crt",
			KeyPath:  "/etc/tripwire/agent.key",
			CAPath:   "/etc/tripwire/ca.crt",
		},
		LogLevel:   "info",
		HealthAddr: "127.0.0.1:9000",
	}
}

func noopLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError + 10}))
}

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

func TestAgent_StartStop_NoComponents(t *testing.T) {
	ag := agent.New(minimalConfig(), noopLogger())

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Start returned unexpected error: %v", err)
	}

	ag.Stop()
	// Stopping a second time must be safe (no panic, no error).
	ag.Stop()
}

func TestAgent_StartReturnsErrorWhenTransportFails(t *testing.T) {
	transport := &fakeTransport{startErr: errors.New("dial failed")}
	ag := agent.New(minimalConfig(), noopLogger(),
		agent.WithTransport(transport),
	)

	err := ag.Start(context.Background())
	if err == nil {
		t.Fatal("expected error when transport fails to start, got nil")
	}
}

func TestAgent_StartReturnsErrorWhenWatcherFails(t *testing.T) {
	w := newFakeWatcher()
	w.startErr = errors.New("inotify unavailable")
	ag := agent.New(minimalConfig(), noopLogger(),
		agent.WithWatchers(w),
	)

	err := ag.Start(context.Background())
	if err == nil {
		t.Fatal("expected error when watcher fails to start, got nil")
	}
}

func TestAgent_EventFlowToQueueAndTransport(t *testing.T) {
	w := newFakeWatcher()
	q := &fakeQueue{}
	tr := &fakeTransport{}

	ag := agent.New(minimalConfig(), noopLogger(),
		agent.WithWatchers(w),
		agent.WithQueue(q),
		agent.WithTransport(tr),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     "etc-passwd-watch",
		Severity:     "CRITICAL",
		Timestamp:    time.Now(),
		Detail:       map[string]any{"path": "/etc/passwd"},
	}
	w.events <- evt

	// Give the processing goroutine a moment to handle the event.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if len(q.enqueued) > 0 && len(tr.sent) > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	ag.Stop()

	if len(q.enqueued) != 1 {
		t.Errorf("queue.enqueued = %d, want 1", len(q.enqueued))
	}
	if len(tr.sent) != 1 {
		t.Errorf("transport.sent = %d, want 1", len(tr.sent))
	}
	if !tr.stopped {
		t.Error("transport.Stop was not called")
	}
}

func TestAgent_HealthzEndpoint_Returns200WithJSON(t *testing.T) {
	ag := agent.New(minimalConfig(), noopLogger())

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer ag.Stop()

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	ag.HealthzHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("Content-Type = %q, want %q", ct, "application/json")
	}

	var h agent.HealthStatus
	if err := json.NewDecoder(rec.Body).Decode(&h); err != nil {
		t.Fatalf("decode health response: %v", err)
	}
	if h.Status != "ok" {
		t.Errorf("status = %q, want %q", h.Status, "ok")
	}
	if h.UptimeS < 0 {
		t.Errorf("uptime_s = %f, must be >= 0", h.UptimeS)
	}
}

func TestAgent_HealthzEndpoint_QueueDepth(t *testing.T) {
	q := &fakeQueue{enqueued: []agent.AlertEvent{{}, {}}} // pre-populate 2 events
	ag := agent.New(minimalConfig(), noopLogger(),
		agent.WithQueue(q),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer ag.Stop()

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	ag.HealthzHandler(rec, req)

	var h agent.HealthStatus
	if err := json.NewDecoder(rec.Body).Decode(&h); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if h.QueueDepth != 2 {
		t.Errorf("queue_depth = %d, want 2", h.QueueDepth)
	}
}

func TestAgent_HealthzEndpoint_LastAlertAt(t *testing.T) {
	w := newFakeWatcher()
	ag := agent.New(minimalConfig(), noopLogger(),
		agent.WithWatchers(w),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	alertTime := time.Now().Round(time.Second)
	w.events <- agent.AlertEvent{
		TripwireType: "PROCESS",
		RuleName:     "bash-watch",
		Severity:     "INFO",
		Timestamp:    alertTime,
	}

	// Wait for the event to be processed.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
		ag.HealthzHandler(rec, req)

		var h agent.HealthStatus
		if err := json.NewDecoder(rec.Body).Decode(&h); err == nil && h.LastAlertAt != "" {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	ag.HealthzHandler(rec, req)

	var h agent.HealthStatus
	if err := json.NewDecoder(rec.Body).Decode(&h); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if h.LastAlertAt == "" {
		t.Error("last_alert_at should be non-empty after an alert was processed")
	}

	ag.Stop()
}

func TestAgent_CannotStartTwice(t *testing.T) {
	ag := agent.New(minimalConfig(), noopLogger())
	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	defer ag.Stop()

	if err := ag.Start(ctx); err == nil {
		t.Fatal("expected error on second Start, got nil")
	}
}
