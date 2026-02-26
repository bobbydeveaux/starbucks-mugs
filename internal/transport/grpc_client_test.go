package transport_test

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"google.golang.org/grpc"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/queue"
	"github.com/tripwire/agent/internal/transport"
	alertpb "github.com/tripwire/agent/proto/alert"
)

// ---------------------------------------------------------------------------
// Mock gRPC server
// ---------------------------------------------------------------------------

// mockAlertServer is a minimal AlertServiceServer for tests.  It records
// every received AgentEvent and sends an ACK for each one.
//
// When closeFirstStreamAfterNEvents > 0 the FIRST stream handler returns
// io.EOF (no ACK) after receiving that many events within a single stream
// invocation.  Subsequent stream invocations always ACK every event normally.
// This allows tests to simulate a transient server error without causing an
// infinite reconnect loop.
type mockAlertServer struct {
	alertpb.UnimplementedAlertServiceServer

	mu     sync.Mutex
	events []*alertpb.AgentEvent

	// closeFirstStreamAfterNEvents causes the first StreamAlerts invocation to
	// return io.EOF (without an ACK) after receiving this many events per
	// stream.  Zero means never force-close.
	closeFirstStreamAfterNEvents int

	// firstStreamClosed is set to true after the first forced close.
	// Subsequent stream invocations see it as true and do not force-close.
	firstStreamClosed atomic.Bool
}

func (s *mockAlertServer) RegisterAgent(_ context.Context, _ *alertpb.RegisterRequest) (*alertpb.RegisterResponse, error) {
	return &alertpb.RegisterResponse{
		HostId:       "test-host-id",
		ServerTimeUs: time.Now().UnixMicro(),
	}, nil
}

func (s *mockAlertServer) StreamAlerts(stream alertpb.AlertService_StreamAlertsServer) error {
	perStreamCount := 0

	for {
		evt, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}

		s.mu.Lock()
		s.events = append(s.events, evt)
		s.mu.Unlock()

		perStreamCount++

		// Force-close ONLY the first stream invocation, and only after
		// receiving the configured number of per-stream events.
		if s.closeFirstStreamAfterNEvents > 0 &&
			perStreamCount >= s.closeFirstStreamAfterNEvents &&
			s.firstStreamClosed.CompareAndSwap(false, true) {
			// Return without sending an ACK so the client has to retry.
			return io.EOF
		}

		// Normal case: send ACK.
		payload, _ := json.Marshal(map[string]string{"alert_id": evt.AlertId})
		if sendErr := stream.Send(&alertpb.ServerCommand{Type: "ACK", Payload: payload}); sendErr != nil {
			return sendErr
		}
	}
}

// recordedRuleNames returns the RuleName of each received event in order.
func (s *mockAlertServer) recordedRuleNames() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	names := make([]string, len(s.events))
	for i, e := range s.events {
		names[i] = e.RuleName
	}
	return names
}

// recordedCount returns the total number of events received so far.
func (s *mockAlertServer) recordedCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.events)
}

// ---------------------------------------------------------------------------
// Server launch helper
// ---------------------------------------------------------------------------

// startInsecureServer starts an in-process gRPC server (no TLS) on a random
// OS-assigned port and registers svc.  The server is stopped when t completes.
func startInsecureServer(t *testing.T, svc alertpb.AlertServiceServer) string {
	t.Helper()

	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}

	gs := grpc.NewServer()
	alertpb.RegisterAlertServiceServer(gs, svc)

	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = gs.Serve(lis)
	}()

	t.Cleanup(func() {
		gs.GracefulStop()
		<-done
	})

	return lis.Addr().String()
}

// ---------------------------------------------------------------------------
// Client helper
// ---------------------------------------------------------------------------

// newInsecureClient creates a GRPCClient configured for insecure (no TLS)
// communication.
func newInsecureClient(addr string, q transport.DrainQueue, logger *slog.Logger) *transport.GRPCClient {
	cfg := transport.ClientConfig{
		Addr:         addr,
		Hostname:     "test-agent",
		Platform:     "linux",
		AgentVersion: "0.0.1-test",
		MaxBackoff:   200 * time.Millisecond, // speed up reconnects in tests
		Insecure:     true,
	}
	return transport.New(cfg, q, logger)
}

// noopLogger returns a logger that discards all output.
func noopLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// ---------------------------------------------------------------------------
// Queue helpers
// ---------------------------------------------------------------------------

// openMemQueue opens an in-memory SQLiteQueue and registers cleanup.
func openMemQueue(t *testing.T) *queue.SQLiteQueue {
	t.Helper()
	q, err := queue.New(":memory:")
	if err != nil {
		t.Fatalf("queue.New: %v", err)
	}
	t.Cleanup(func() { _ = q.Close() })
	return q
}

// enqueueN adds n events with sequential rule names (rule-0, rule-1, …) to q.
func enqueueN(t *testing.T, q *queue.SQLiteQueue, n int) {
	t.Helper()
	ctx := context.Background()
	for i := range n {
		evt := agent.AlertEvent{
			TripwireType: "FILE",
			RuleName:     "rule-" + itoa(i),
			Severity:     "INFO",
			Timestamp:    time.Now().UTC(),
			Detail:       map[string]any{"index": i},
		}
		if err := q.Enqueue(ctx, evt); err != nil {
			t.Fatalf("Enqueue %d: %v", i, err)
		}
	}
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

// waitFor polls cond every 10 ms until it returns true or deadline is reached.
func waitFor(t *testing.T, timeout time.Duration, cond func() bool) bool {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

// itoa converts a non-negative integer to its decimal string representation
// without importing strconv.
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	const digits = "0123456789"
	buf := make([]byte, 0, 8)
	for n > 0 {
		buf = append([]byte{digits[n%10]}, buf...)
		n /= 10
	}
	return string(buf)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// TestGRPCClient_QueueDrainOnConnect verifies that all events pending in the
// SQLite queue are delivered to the server (oldest first) immediately after
// the bidirectional stream is established.
func TestGRPCClient_QueueDrainOnConnect(t *testing.T) {
	const numEvents = 5

	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	q := openMemQueue(t)
	enqueueN(t, q, numEvents)

	client := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// All queued events must be delivered and the queue must reach depth 0.
	if !waitFor(t, 5*time.Second, func() bool {
		return svc.recordedCount() == numEvents && q.Depth() == 0
	}) {
		t.Fatalf("timed out: server received %d events (want %d), queue depth=%d (want 0)",
			svc.recordedCount(), numEvents, q.Depth())
	}

	cancel()
	client.Stop()

	// Verify FIFO delivery order.
	got := svc.recordedRuleNames()
	for i, name := range got {
		want := "rule-" + itoa(i)
		if name != want {
			t.Errorf("event[%d].RuleName = %q, want %q", i, name, want)
		}
	}
}

// TestGRPCClient_AlertsSentTotalCountsACKedEvents verifies that
// AlertsSentTotal increments for every server ACK across both the queue-drain
// path and the live-event path.
func TestGRPCClient_AlertsSentTotalCountsACKedEvents(t *testing.T) {
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	q := openMemQueue(t)
	enqueueN(t, q, 2) // two queued events

	client := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Both queued events must be ACKed.
	if !waitFor(t, 5*time.Second, func() bool {
		return client.AlertsSentTotal() >= 2
	}) {
		t.Fatalf("AlertsSentTotal=%d after queued events, want >=2", client.AlertsSentTotal())
	}

	// Send two more events via the live path.
	liveEvt := agent.AlertEvent{
		TripwireType: "NETWORK",
		RuleName:     "live-rule",
		Severity:     "WARN",
		Timestamp:    time.Now().UTC(),
	}
	for i := 0; i < 2; i++ {
		// Retry until the live channel accepts the event.
		ok := waitFor(t, 2*time.Second, func() bool {
			return client.Send(ctx, liveEvt) == nil
		})
		if !ok {
			t.Fatalf("Send(%d) failed: channel not ready within timeout", i)
		}
	}

	// All four events (2 queued + 2 live) must be ACKed.
	if !waitFor(t, 5*time.Second, func() bool {
		return client.AlertsSentTotal() >= 4
	}) {
		t.Fatalf("AlertsSentTotal=%d, want >=4", client.AlertsSentTotal())
	}

	cancel()
	client.Stop()
}

// TestGRPCClient_QueueDepthReflectsUndeliveredRows verifies that QueueDepth
// returns the SQLite queue's pending-event count.
func TestGRPCClient_QueueDepthReflectsUndeliveredRows(t *testing.T) {
	q := openMemQueue(t)
	enqueueN(t, q, 3)

	// QueueDepth must reflect the 3 pending events even before Start.
	cfg := transport.ClientConfig{
		Addr:     "127.0.0.1:1", // unreachable; we only call QueueDepth
		Insecure: true,
	}
	client := transport.New(cfg, q, noopLogger())

	if d := client.QueueDepth(); d != 3 {
		t.Errorf("QueueDepth=%d before delivery, want 3", d)
	}

	// After drain via a real server, depth should reach 0.
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)
	client2 := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client2.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	if !waitFor(t, 5*time.Second, func() bool {
		return client2.QueueDepth() == 0
	}) {
		t.Errorf("QueueDepth=%d after drain, want 0", client2.QueueDepth())
	}

	cancel()
	client2.Stop()
}

// TestGRPCClient_StreamErrorTriggersReconnect verifies that a server-side
// stream error causes the client to re-enter the backoff loop
// (ReconnectTotal increments) and eventually delivers all queued events.
//
// The mock server closes the FIRST stream after 1 event (without sending
// an ACK).  The client reconnects; on the second connection the server ACKs
// all events normally, so all three events are eventually delivered.
func TestGRPCClient_StreamErrorTriggersReconnect(t *testing.T) {
	// Close only the first stream after 1 event to trigger one reconnect.
	svc := &mockAlertServer{closeFirstStreamAfterNEvents: 1}
	addr := startInsecureServer(t, svc)

	q := openMemQueue(t)
	enqueueN(t, q, 3)

	client := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// After the forced disconnect and reconnect, all events reach the server
	// (event-1 is resent) and the queue is drained to 0.
	if !waitFor(t, 10*time.Second, func() bool {
		return q.Depth() == 0
	}) {
		t.Fatalf("queue not drained: depth=%d", q.Depth())
	}

	// At least one reconnect must have occurred.
	if client.ReconnectTotal() < 1 {
		t.Errorf("ReconnectTotal=%d, want >=1", client.ReconnectTotal())
	}

	// Server must have received at least 3 events (event-1 may arrive twice).
	if svc.recordedCount() < 3 {
		t.Errorf("server received %d events, want >=3", svc.recordedCount())
	}

	cancel()
	client.Stop()
}

// TestGRPCClient_NoQueue_LiveEventsDelivered verifies that the transport works
// without a queue: live events sent via Send are delivered normally.
func TestGRPCClient_NoQueue_LiveEventsDelivered(t *testing.T) {
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	// No queue provided.
	client := newInsecureClient(addr, nil, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	evt := agent.AlertEvent{
		TripwireType: "PROCESS",
		RuleName:     "bash-watch",
		Severity:     "WARN",
		Timestamp:    time.Now().UTC(),
	}

	// Retry until the live channel is available.
	if !waitFor(t, 3*time.Second, func() bool {
		return client.Send(ctx, evt) == nil
	}) {
		t.Fatal("Send failed: channel not ready within timeout")
	}

	if !waitFor(t, 5*time.Second, func() bool {
		return svc.recordedCount() >= 1
	}) {
		t.Fatalf("server received %d events, want >=1", svc.recordedCount())
	}

	cancel()
	client.Stop()
}

// TestGRPCClient_StopIsIdempotent verifies that Stop may be called multiple
// times without panicking.
func TestGRPCClient_StopIsIdempotent(t *testing.T) {
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	client := newInsecureClient(addr, nil, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	client.Stop()
	client.Stop() // must not panic
}

// TestGRPCClient_HostIDSetAfterRegister verifies that HostID returns a
// non-empty string once the client has successfully registered.
func TestGRPCClient_HostIDSetAfterRegister(t *testing.T) {
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	client := newInsecureClient(addr, nil, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	if !waitFor(t, 5*time.Second, func() bool {
		return client.HostID() != ""
	}) {
		t.Error("HostID is empty after timeout; want non-empty after registration")
	}

	cancel()
	client.Stop()

	if id := client.HostID(); id != "test-host-id" {
		t.Errorf("HostID = %q, want %q", id, "test-host-id")
	}
}

// TestGRPCClient_SendReturnsErrorAfterStop verifies that Send returns an error
// once Stop has been called.
func TestGRPCClient_SendReturnsErrorAfterStop(t *testing.T) {
	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	client := newInsecureClient(addr, nil, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	client.Stop()

	err := client.Send(ctx, agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     "test",
		Severity:     "INFO",
		Timestamp:    time.Now(),
	})
	if err == nil {
		t.Error("Send after Stop returned nil, want error")
	}
}

// TestGRPCClient_QueueDrainOrdering_MultiBatch verifies FIFO delivery order
// for more events than drainBatchSize (50), requiring multiple dequeue rounds.
func TestGRPCClient_QueueDrainOrdering_MultiBatch(t *testing.T) {
	const n = 75 // larger than drainBatchSize

	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	q := openMemQueue(t)
	enqueueN(t, q, n)

	client := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	if !waitFor(t, 10*time.Second, func() bool {
		return svc.recordedCount() == n && q.Depth() == 0
	}) {
		t.Fatalf("timed out: server received %d/%d events, queue depth=%d",
			svc.recordedCount(), n, q.Depth())
	}

	cancel()
	client.Stop()

	got := svc.recordedRuleNames()
	if len(got) != n {
		t.Fatalf("recorded %d events, want %d", len(got), n)
	}
	for i, name := range got {
		want := "rule-" + itoa(i)
		if name != want {
			t.Errorf("event[%d].RuleName = %q, want %q", i, name, want)
		}
	}
}

// TestGRPCClient_MetricsAfterQueueDrain verifies that AlertsSentTotal equals
// the number of queued events after a full drain, and that QueueDepth is 0.
func TestGRPCClient_MetricsAfterQueueDrain(t *testing.T) {
	const n = 10

	svc := &mockAlertServer{}
	addr := startInsecureServer(t, svc)

	q := openMemQueue(t)
	enqueueN(t, q, n)

	client := newInsecureClient(addr, q, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := client.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	if !waitFor(t, 5*time.Second, func() bool {
		return client.AlertsSentTotal() == int64(n) && client.QueueDepth() == 0
	}) {
		t.Errorf("AlertsSentTotal=%d (want %d), QueueDepth=%d (want 0)",
			client.AlertsSentTotal(), n, client.QueueDepth())
	}

	cancel()
	client.Stop()

	// ReconnectTotal must be 0 — no connection errors occurred.
	if r := client.ReconnectTotal(); r != 0 {
		t.Errorf("ReconnectTotal=%d, want 0 (no errors expected)", r)
	}
}

// TestGRPCClient_InterfaceCompliance is a compile-time check that *GRPCClient
// implements agent.Transport.
func TestGRPCClient_InterfaceCompliance(t *testing.T) {
	var _ agent.Transport = (*transport.GRPCClient)(nil)
}
