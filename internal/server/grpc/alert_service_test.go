package grpc_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sync"
	"testing"
	"time"

	grpccode "google.golang.org/grpc/codes"
	grpcmeta "google.golang.org/grpc/metadata"
	grpcstatus "google.golang.org/grpc/status"

	svcgrpc "github.com/tripwire/agent/internal/server/grpc"
	"github.com/tripwire/agent/internal/server/storage"
	wsbcast "github.com/tripwire/agent/internal/server/websocket"
	alertpb "github.com/tripwire/agent/proto/alert"
)

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

// mockStore records UpsertHost and BatchInsertAlerts calls.
type mockStore struct {
	mu           sync.Mutex
	hosts        []storage.Host
	alerts       []storage.Alert
	upsertErr    error
	batchErr     error
}

func (m *mockStore) UpsertHost(_ context.Context, h storage.Host) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.upsertErr != nil {
		return m.upsertErr
	}
	m.hosts = append(m.hosts, h)
	return nil
}

func (m *mockStore) BatchInsertAlerts(_ context.Context, a storage.Alert) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.batchErr != nil {
		return m.batchErr
	}
	m.alerts = append(m.alerts, a)
	return nil
}

// mockStream is a hand-rolled alertpb.AlertService_StreamAlertsServer for
// unit testing without a real gRPC network connection.
type mockStream struct {
	ctx context.Context

	mu     sync.Mutex
	events []*alertpb.AgentEvent // queued inbound events
	sent   []*alertpb.ServerCommand
	recvAt int
}

func newMockStream(ctx context.Context, events ...*alertpb.AgentEvent) *mockStream {
	return &mockStream{ctx: ctx, events: events}
}

// Context implements grpc.ServerStream.
func (m *mockStream) Context() context.Context { return m.ctx }

// Recv returns events one by one, then io.EOF.
func (m *mockStream) Recv() (*alertpb.AgentEvent, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.recvAt >= len(m.events) {
		return nil, io.EOF
	}
	evt := m.events[m.recvAt]
	m.recvAt++
	return evt, nil
}

// Send records the outbound ServerCommand.
func (m *mockStream) Send(cmd *alertpb.ServerCommand) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sent = append(m.sent, cmd)
	return nil
}

// grpc.ServerStream boilerplate — unused in these tests.
func (m *mockStream) SendMsg(msg interface{}) error        { return nil }
func (m *mockStream) RecvMsg(msg interface{}) error        { return nil }
func (m *mockStream) SendHeader(md grpcmeta.MD) error      { return nil }
func (m *mockStream) SetHeader(md grpcmeta.MD) error       { return nil }
func (m *mockStream) SetTrailer(md grpcmeta.MD)             {}

// stubBroadcaster records Publish calls for assertions.
type stubBroadcaster struct {
	mu      sync.Mutex
	alerts  []storage.Alert
	ch      chan storage.Alert
}

func newStubBroadcaster() *stubBroadcaster {
	return &stubBroadcaster{ch: make(chan storage.Alert, 64)}
}

func (b *stubBroadcaster) Publish(a storage.Alert) {
	b.mu.Lock()
	b.alerts = append(b.alerts, a)
	b.mu.Unlock()
	// Also write to channel so callers can do a channel-receive assertion.
	select {
	case b.ch <- a:
	default:
	}
}

func (b *stubBroadcaster) received() []storage.Alert {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]storage.Alert, len(b.alerts))
	copy(out, b.alerts)
	return out
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func newLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

func validEvent(t *testing.T) *alertpb.AgentEvent {
	t.Helper()
	detail, _ := json.Marshal(map[string]string{"path": "/etc/passwd"})
	return &alertpb.AgentEvent{
		AlertId:         "aaaaaaaa-0000-0000-0000-000000000001",
		HostId:          "host-001",
		TimestampUs:     time.Now().UnixMicro(),
		TripwireType:    "FILE",
		RuleName:        "etc-passwd-watch",
		EventDetailJson: detail,
		Severity:        "CRITICAL",
	}
}

// ---------------------------------------------------------------------------
// RegisterAgent tests
// ---------------------------------------------------------------------------

func TestRegisterAgent_HappyPath(t *testing.T) {
	store := &mockStore{}
	bcast := newStubBroadcaster()
	svc := svcgrpc.NewAlertService(store, bcast, newLogger(), 300)

	resp, err := svc.RegisterAgent(context.Background(), &alertpb.RegisterRequest{
		Hostname:     "web-01",
		Platform:     "linux",
		AgentVersion: "1.0.0",
	})
	if err != nil {
		t.Fatalf("RegisterAgent returned unexpected error: %v", err)
	}
	if resp.GetHostId() == "" {
		t.Error("RegisterAgent: expected non-empty host_id in response")
	}
	if resp.GetServerTimeUs() == 0 {
		t.Error("RegisterAgent: expected non-zero server_time_us in response")
	}
	if len(store.hosts) != 1 {
		t.Errorf("RegisterAgent: expected 1 upserted host, got %d", len(store.hosts))
	}
}

func TestRegisterAgent_EmptyHostname(t *testing.T) {
	svc := svcgrpc.NewAlertService(&mockStore{}, newStubBroadcaster(), newLogger(), 0)
	_, err := svc.RegisterAgent(context.Background(), &alertpb.RegisterRequest{Hostname: ""})
	if err == nil {
		t.Fatal("expected error for empty hostname, got nil")
	}
	st, _ := grpcstatus.FromError(err)
	if st.Code() != grpccode.InvalidArgument {
		t.Errorf("expected InvalidArgument, got %s", st.Code())
	}
}

// ---------------------------------------------------------------------------
// StreamAlerts — happy path
// ---------------------------------------------------------------------------

// TestStreamAlerts_PersistsAndBroadcasts verifies that a valid AgentEvent is:
//  1. Persisted to the store.
//  2. Published to the broadcaster (acceptance criterion §1).
//  3. Responded to with an ACK.
func TestStreamAlerts_PersistsAndBroadcasts(t *testing.T) {
	store := &mockStore{}
	bcast := newStubBroadcaster()
	svc := svcgrpc.NewAlertService(store, bcast, newLogger(), 300)

	evt := validEvent(t)
	stream := newMockStream(context.Background(), evt)

	if err := svc.StreamAlerts(stream); err != nil {
		t.Fatalf("StreamAlerts returned error: %v", err)
	}

	// Verify persistence.
	if len(store.alerts) != 1 {
		t.Errorf("expected 1 persisted alert, got %d", len(store.alerts))
	}

	// Verify broadcaster received the alert (criterion §1).
	select {
	case a := <-bcast.ch:
		if a.AlertID != evt.GetAlertId() {
			t.Errorf("broadcast alert_id = %q; want %q", a.AlertID, evt.GetAlertId())
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for broadcast")
	}

	// Verify ACK was sent back.
	stream.mu.Lock()
	defer stream.mu.Unlock()
	if len(stream.sent) != 1 || stream.sent[0].GetType() != "ACK" {
		t.Errorf("expected 1 ACK response, got %+v", stream.sent)
	}
}

// ---------------------------------------------------------------------------
// StreamAlerts — non-blocking fan-out
// ---------------------------------------------------------------------------

// TestStreamAlerts_SlowSubscriberDoesNotBlock verifies acceptance criterion §2:
// a subscriber whose buffer is full must not block the gRPC stream goroutine.
func TestStreamAlerts_SlowSubscriberDoesNotBlock(t *testing.T) {
	logger := newLogger()
	// Use a real broadcaster with a buffer of 1 so it fills immediately.
	bcast := wsbcast.NewBroadcaster(logger, 1)
	// Subscribe and intentionally do NOT read from the channel.
	_ = bcast.Subscribe(context.Background())

	store := &mockStore{}
	svc := svcgrpc.NewAlertService(store, bcast, logger, 300)

	// Send 10 events — more than the subscriber buffer depth.
	events := make([]*alertpb.AgentEvent, 10)
	for i := range events {
		evt := validEvent(t)
		evt.AlertId = fmt.Sprintf("aaaaaaaa-0000-0000-0000-%012d", i+1)
		events[i] = evt
	}

	stream := newMockStream(context.Background(), events...)

	done := make(chan error, 1)
	go func() { done <- svc.StreamAlerts(stream) }()

	select {
	case err := <-done:
		if err != nil {
			t.Errorf("StreamAlerts returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("StreamAlerts blocked due to slow WebSocket subscriber (criterion §2 violated)")
	}

	// All 10 events should still be persisted even if some broadcasts dropped.
	if len(store.alerts) != 10 {
		t.Errorf("expected 10 persisted alerts, got %d", len(store.alerts))
	}
}

// ---------------------------------------------------------------------------
// StreamAlerts — validation
// ---------------------------------------------------------------------------

func TestStreamAlerts_InvalidTripwireType(t *testing.T) {
	store := &mockStore{}
	bcast := newStubBroadcaster()
	svc := svcgrpc.NewAlertService(store, bcast, newLogger(), 300)

	evt := validEvent(t)
	evt.TripwireType = "UNKNOWN"

	stream := newMockStream(context.Background(), evt)
	// StreamAlerts must NOT return an error for invalid events; it sends an
	// ERROR ACK instead and continues processing the stream.
	if err := svc.StreamAlerts(stream); err != nil {
		t.Fatalf("StreamAlerts should not return error for invalid event; got %v", err)
	}

	// Event must not be persisted.
	if len(store.alerts) != 0 {
		t.Error("invalid event must not be persisted")
	}
	// Broadcaster must not be called.
	if len(bcast.received()) != 0 {
		t.Error("broadcaster must not receive invalid event")
	}
	// An ERROR ACK must be sent back to the agent.
	stream.mu.Lock()
	defer stream.mu.Unlock()
	if len(stream.sent) == 0 || stream.sent[0].GetType() != "ERROR" {
		t.Errorf("expected ERROR ACK for invalid tripwire_type, got %+v", stream.sent)
	}
}

func TestStreamAlerts_StaleTimestamp(t *testing.T) {
	store := &mockStore{}
	svc := svcgrpc.NewAlertService(store, newStubBroadcaster(), newLogger(), 300)

	evt := validEvent(t)
	// Set timestamp 10 minutes in the past — beyond the 5-minute window.
	evt.TimestampUs = time.Now().Add(-10 * time.Minute).UnixMicro()

	stream := newMockStream(context.Background(), evt)
	_ = svc.StreamAlerts(stream)

	if len(store.alerts) != 0 {
		t.Error("stale event must not be persisted")
	}
	stream.mu.Lock()
	defer stream.mu.Unlock()
	if len(stream.sent) == 0 || stream.sent[0].GetType() != "ERROR" {
		t.Errorf("expected ERROR ACK for stale timestamp, got %+v", stream.sent)
	}
}

func TestStreamAlerts_MissingAlertID(t *testing.T) {
	store := &mockStore{}
	svc := svcgrpc.NewAlertService(store, newStubBroadcaster(), newLogger(), 300)

	evt := validEvent(t)
	evt.AlertId = ""

	stream := newMockStream(context.Background(), evt)
	_ = svc.StreamAlerts(stream)

	if len(store.alerts) != 0 {
		t.Error("event without alert_id must not be persisted")
	}
}

// ---------------------------------------------------------------------------
// StreamAlerts — store error propagation
// ---------------------------------------------------------------------------

func TestStreamAlerts_StoreError_SendsErrorACK(t *testing.T) {
	store := &mockStore{batchErr: fmt.Errorf("DB connection lost")}
	bcast := newStubBroadcaster()
	svc := svcgrpc.NewAlertService(store, bcast, newLogger(), 300)

	stream := newMockStream(context.Background(), validEvent(t))
	_ = svc.StreamAlerts(stream)

	// An error ACK should be sent; the broadcaster must NOT be called.
	if len(bcast.received()) != 0 {
		t.Error("broadcaster must not be called when persist fails")
	}
	stream.mu.Lock()
	defer stream.mu.Unlock()
	if len(stream.sent) == 0 || stream.sent[0].GetType() != "ERROR" {
		t.Errorf("expected ERROR ACK after store failure, got %+v", stream.sent)
	}
}

// ---------------------------------------------------------------------------
// Broadcaster unit tests
// ---------------------------------------------------------------------------

func TestBroadcaster_Subscribe_Publish_Unsubscribe(t *testing.T) {
	b := wsbcast.NewBroadcaster(newLogger(), 8)
	defer b.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ch := b.Subscribe(ctx)

	alert := storage.Alert{
		AlertID:  "test-id",
		HostID:   "host-01",
		Severity: storage.SeverityCritical,
	}
	b.Publish(alert)

	select {
	case got := <-ch:
		if got.AlertID != alert.AlertID {
			t.Errorf("got alert_id %q; want %q", got.AlertID, alert.AlertID)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for published alert")
	}
}

func TestBroadcaster_SlowConsumer_DropsNotBlocks(t *testing.T) {
	b := wsbcast.NewBroadcaster(newLogger(), 1)
	defer b.Close()

	// Subscribe but never read.
	_ = b.Subscribe(context.Background())

	alert := storage.Alert{AlertID: "x"}
	done := make(chan struct{})
	go func() {
		// Publish many more alerts than the buffer depth.
		for i := 0; i < 100; i++ {
			b.Publish(alert)
		}
		close(done)
	}()

	select {
	case <-done:
		// Good: Publish did not block.
	case <-time.After(2 * time.Second):
		t.Fatal("Publish blocked on slow subscriber")
	}
}

func TestBroadcaster_ContextCancelUnsubscribes(t *testing.T) {
	b := wsbcast.NewBroadcaster(newLogger(), 8)
	defer b.Close()

	ctx, cancel := context.WithCancel(context.Background())
	ch := b.Subscribe(ctx)

	// Cancel the context — the broadcaster should close ch.
	cancel()

	// Give the goroutine time to react.
	select {
	case _, open := <-ch:
		if open {
			t.Error("expected channel to be closed after context cancel")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("channel was not closed after context cancel")
	}
}

func TestBroadcaster_Close_ClosesAllSubscribers(t *testing.T) {
	b := wsbcast.NewBroadcaster(newLogger(), 8)

	ch1 := b.Subscribe(context.Background())
	ch2 := b.Subscribe(context.Background())

	b.Close()

	for _, ch := range []<-chan storage.Alert{ch1, ch2} {
		select {
		case _, open := <-ch:
			if open {
				t.Error("expected closed channel after broadcaster.Close()")
			}
		case <-time.After(time.Second):
			t.Fatal("channel not closed after broadcaster.Close()")
		}
	}
}

// ---------------------------------------------------------------------------
// Integration: ingested event appears on a WebSocket subscriber channel
// (acceptance criterion §3)
// ---------------------------------------------------------------------------

// TestIntegration_IngestedEventAppearsOnWebSocketSubscription is the
// end-to-end integration test required by acceptance criterion §3.
// It wires a real InProcessBroadcaster to the AlertService, subscribes a
// simulated WebSocket client, injects an AgentEvent through the gRPC stream
// handler, and verifies the alert reaches the subscription channel.
func TestIntegration_IngestedEventAppearsOnWebSocketSubscription(t *testing.T) {
	logger := newLogger()
	store := &mockStore{}
	bcast := wsbcast.NewBroadcaster(logger, 32)
	defer bcast.Close()

	svc := svcgrpc.NewAlertService(store, bcast, logger, 300)

	// Simulate a browser WebSocket client subscribing.
	clientCtx, clientCancel := context.WithCancel(context.Background())
	defer clientCancel()
	subscription := bcast.Subscribe(clientCtx)

	// Inject a valid AgentEvent through the gRPC stream handler.
	evt := validEvent(t)
	stream := newMockStream(context.Background(), evt)

	if err := svc.StreamAlerts(stream); err != nil {
		t.Fatalf("StreamAlerts returned error: %v", err)
	}

	// The WebSocket subscriber (criterion §3) must receive the alert.
	select {
	case a := <-subscription:
		if a.AlertID != evt.GetAlertId() {
			t.Errorf("subscriber received alert_id %q; want %q", a.AlertID, evt.GetAlertId())
		}
		if a.Severity != storage.SeverityCritical {
			t.Errorf("subscriber received severity %q; want CRITICAL", a.Severity)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("WebSocket subscriber did not receive alert within 2s (criterion §3 violated)")
	}
}
