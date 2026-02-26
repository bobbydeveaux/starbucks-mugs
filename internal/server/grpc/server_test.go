package grpc_test

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"testing"
	"time"

	"google.golang.org/grpc/metadata"

	"github.com/tripwire/agent/internal/server/grpc"
	"github.com/tripwire/agent/internal/server/grpc/alertpb"
	"github.com/tripwire/agent/internal/server/storage"
	ws "github.com/tripwire/agent/internal/server/websocket"
)

// --- fakes -------------------------------------------------------------------

// fakeStore satisfies grpc.Store without a real database.
type fakeStore struct {
	hosts         map[string]storage.Host // keyed by HostID
	insertedAlerts []storage.Alert
	upsertErr     error
	insertErr     error
}

func newFakeStore() *fakeStore {
	return &fakeStore{hosts: make(map[string]storage.Host)}
}

func (f *fakeStore) UpsertHost(_ context.Context, h storage.Host) (string, error) {
	if f.upsertErr != nil {
		return "", f.upsertErr
	}
	// Check if a host with the same hostname already exists and return its
	// stable host_id, mirroring the ON CONFLICT … RETURNING behaviour of the
	// real PostgreSQL implementation.
	for _, existing := range f.hosts {
		if existing.Hostname == h.Hostname {
			// Update mutable fields on the existing record.
			existing.Platform = h.Platform
			existing.AgentVersion = h.AgentVersion
			existing.LastSeen = h.LastSeen
			existing.Status = h.Status
			f.hosts[existing.HostID] = existing
			return existing.HostID, nil
		}
	}
	f.hosts[h.HostID] = h
	return h.HostID, nil
}

func (f *fakeStore) GetHost(_ context.Context, hostID string) (*storage.Host, error) {
	h, ok := f.hosts[hostID]
	if !ok {
		return nil, context.DeadlineExceeded // simulate not-found
	}
	return &h, nil
}

func (f *fakeStore) BatchInsertAlerts(_ context.Context, alert storage.Alert) error {
	if f.insertErr != nil {
		return f.insertErr
	}
	f.insertedAlerts = append(f.insertedAlerts, alert)
	return nil
}

// fakeStream satisfies alertpb.AlertService_StreamAlertsServer for testing.
type fakeStream struct {
	events []*alertpb.AgentEvent
	pos    int
	sent   []*alertpb.ServerCommand
	ctx    context.Context
}

func newFakeStream(ctx context.Context, events ...*alertpb.AgentEvent) *fakeStream {
	return &fakeStream{events: events, ctx: ctx}
}

func (f *fakeStream) Recv() (*alertpb.AgentEvent, error) {
	if f.pos >= len(f.events) {
		// Signal EOF so the server exits the loop cleanly.
		return nil, context.Canceled
	}
	evt := f.events[f.pos]
	f.pos++
	return evt, nil
}

func (f *fakeStream) Send(cmd *alertpb.ServerCommand) error {
	f.sent = append(f.sent, cmd)
	return nil
}

// grpc.ServerStream stubs — satisfies google.golang.org/grpc.ServerStream.
func (f *fakeStream) SetHeader(md metadata.MD) error  { return nil }
func (f *fakeStream) SendHeader(md metadata.MD) error { return nil }
func (f *fakeStream) SetTrailer(md metadata.MD)       {}
func (f *fakeStream) Context() context.Context        { return f.ctx }
func (f *fakeStream) SendMsg(m any) error             { return nil }
func (f *fakeStream) RecvMsg(m any) error             { return nil }

// --- helpers -----------------------------------------------------------------

func newTestServer(store grpc.Store) *grpc.Server {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	bc := ws.NewBroadcaster(logger, 16)
	return grpc.NewServer(store, bc, logger)
}

func newTestServerWithBroadcaster(store grpc.Store, bc *ws.Broadcaster) *grpc.Server {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	return grpc.NewServer(store, bc, logger)
}

// --- RegisterAgent tests -----------------------------------------------------

func TestRegisterAgent_Success(t *testing.T) {
	t.Parallel()

	store := newFakeStore()
	srv := newTestServer(store)

	resp, err := srv.RegisterAgent(context.Background(), &alertpb.RegisterRequest{
		Hostname:     "web-01",
		Platform:     "linux",
		AgentVersion: "1.0.0",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.HostId == "" {
		t.Error("expected non-empty host_id in response")
	}
	if resp.ServerTimeUs == 0 {
		t.Error("expected non-zero server_time_us")
	}

	// Verify host was upserted.
	if len(store.hosts) != 1 {
		t.Fatalf("expected 1 upserted host, got %d", len(store.hosts))
	}
	for _, h := range store.hosts {
		if h.Hostname != "web-01" {
			t.Errorf("hostname: got %q, want %q", h.Hostname, "web-01")
		}
		if h.Status != storage.HostStatusOnline {
			t.Errorf("status: got %q, want %q", h.Status, storage.HostStatusOnline)
		}
	}
}

func TestRegisterAgent_StableHostIDOnReconnect(t *testing.T) {
	t.Parallel()

	store := newFakeStore()
	srv := newTestServer(store)

	ctx := context.Background()
	req := &alertpb.RegisterRequest{
		Hostname:     "web-01",
		Platform:     "linux",
		AgentVersion: "1.0.0",
	}

	// First registration — establishes the host record.
	resp1, err := srv.RegisterAgent(ctx, req)
	if err != nil {
		t.Fatalf("first registration: unexpected error: %v", err)
	}
	if resp1.HostId == "" {
		t.Fatal("first registration: expected non-empty host_id")
	}

	// Second registration with the same hostname (agent reconnect) — must
	// return the same host_id so that alert correlation is preserved.
	resp2, err := srv.RegisterAgent(ctx, req)
	if err != nil {
		t.Fatalf("second registration: unexpected error: %v", err)
	}
	if resp2.HostId != resp1.HostId {
		t.Errorf("host_id changed on reconnect: first=%q second=%q", resp1.HostId, resp2.HostId)
	}

	// Exactly one host record must exist — not two.
	if len(store.hosts) != 1 {
		t.Errorf("expected 1 host record, got %d", len(store.hosts))
	}
}

func TestRegisterAgent_MissingHostname(t *testing.T) {
	t.Parallel()

	srv := newTestServer(newFakeStore())
	_, err := srv.RegisterAgent(context.Background(), &alertpb.RegisterRequest{})
	if err == nil {
		t.Fatal("expected error for empty hostname, got nil")
	}
}

// --- StreamAlerts tests ------------------------------------------------------

func validEvent(hostID string) *alertpb.AgentEvent {
	detail, _ := json.Marshal(map[string]string{"path": "/etc/passwd"})
	return &alertpb.AgentEvent{
		AlertId:         "alert-1",
		HostId:          hostID,
		TimestampUs:     time.Now().UnixMicro(),
		TripwireType:    "FILE",
		RuleName:        "etc-passwd-watch",
		EventDetailJson: detail,
		Severity:        "CRITICAL",
	}
}

func TestStreamAlerts_PersistsAndBroadcasts(t *testing.T) {
	t.Parallel()

	store := newFakeStore()
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	bc := ws.NewBroadcaster(logger, 16)
	srv := newTestServerWithBroadcaster(store, bc)

	// Register a host so hostname lookup succeeds.
	hostID := "host-uuid"
	store.hosts[hostID] = storage.Host{HostID: hostID, Hostname: "web-01", Status: storage.HostStatusOnline}

	// Register a WS client to receive broadcast.
	client := bc.Register("browser")
	defer bc.Unregister("browser")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	stream := newFakeStream(ctx, validEvent(hostID))
	err := srv.StreamAlerts(stream)
	// context.Canceled is expected when the fake stream is exhausted.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify alert was persisted.
	if len(store.insertedAlerts) != 1 {
		t.Fatalf("expected 1 inserted alert, got %d", len(store.insertedAlerts))
	}
	a := store.insertedAlerts[0]
	if a.AlertID != "alert-1" {
		t.Errorf("alert_id: got %q, want %q", a.AlertID, "alert-1")
	}
	if a.TripwireType != storage.TripwireTypeFile {
		t.Errorf("tripwire_type: got %q, want %q", a.TripwireType, storage.TripwireTypeFile)
	}
	if a.Severity != storage.SeverityCritical {
		t.Errorf("severity: got %q, want %q", a.Severity, storage.SeverityCritical)
	}

	// Verify WebSocket broadcast was received.
	select {
	case raw, ok := <-client.Send():
		if !ok {
			t.Fatal("broadcast channel closed unexpectedly")
		}
		var msg ws.AlertMessage
		if err := json.Unmarshal(raw, &msg); err != nil {
			t.Fatalf("unmarshal broadcast: %v", err)
		}
		if msg.Type != "alert" {
			t.Errorf("broadcast type: got %q, want %q", msg.Type, "alert")
		}
		if msg.Data.AlertID != "alert-1" {
			t.Errorf("broadcast alert_id: got %q, want %q", msg.Data.AlertID, "alert-1")
		}
		if msg.Data.Hostname != "web-01" {
			t.Errorf("broadcast hostname: got %q, want %q", msg.Data.Hostname, "web-01")
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("timeout waiting for broadcast message")
	}
}

func TestStreamAlerts_InvalidTripwireType(t *testing.T) {
	t.Parallel()

	srv := newTestServer(newFakeStore())
	ctx := context.Background()

	evt := validEvent("host-id")
	evt.TripwireType = "INVALID"

	stream := newFakeStream(ctx, evt)
	err := srv.StreamAlerts(stream)
	if err == nil {
		t.Fatal("expected error for invalid tripwire_type, got nil")
	}
}

func TestStreamAlerts_InvalidSeverity(t *testing.T) {
	t.Parallel()

	srv := newTestServer(newFakeStore())
	ctx := context.Background()

	evt := validEvent("host-id")
	evt.Severity = "EXTREME"

	stream := newFakeStream(ctx, evt)
	err := srv.StreamAlerts(stream)
	if err == nil {
		t.Fatal("expected error for invalid severity, got nil")
	}
}

func TestStreamAlerts_MissingAlertID(t *testing.T) {
	t.Parallel()

	srv := newTestServer(newFakeStore())
	ctx := context.Background()

	evt := validEvent("host-id")
	evt.AlertId = ""

	stream := newFakeStream(ctx, evt)
	err := srv.StreamAlerts(stream)
	if err == nil {
		t.Fatal("expected error for empty alert_id, got nil")
	}
}

func TestStreamAlerts_MissingHostID(t *testing.T) {
	t.Parallel()

	srv := newTestServer(newFakeStore())
	ctx := context.Background()

	evt := validEvent("")
	stream := newFakeStream(ctx, evt)
	err := srv.StreamAlerts(stream)
	if err == nil {
		t.Fatal("expected error for empty host_id, got nil")
	}
}

func TestStreamAlerts_ZeroTimestampDefaultsToNow(t *testing.T) {
	t.Parallel()

	store := newFakeStore()
	srv := newTestServer(store)
	store.hosts["host-id"] = storage.Host{HostID: "host-id", Hostname: "web-01"}

	evt := validEvent("host-id")
	evt.TimestampUs = 0 // zero → server should use current time

	before := time.Now()
	stream := newFakeStream(context.Background(), evt)
	_ = srv.StreamAlerts(stream)
	after := time.Now()

	if len(store.insertedAlerts) != 1 {
		t.Fatalf("expected 1 alert, got %d", len(store.insertedAlerts))
	}
	ts := store.insertedAlerts[0].Timestamp
	if ts.Before(before.Add(-time.Second)) || ts.After(after.Add(time.Second)) {
		t.Errorf("expected timestamp near now, got %v", ts)
	}
}

func TestStreamAlerts_NullEventDetail(t *testing.T) {
	t.Parallel()

	store := newFakeStore()
	srv := newTestServer(store)
	store.hosts["host-id"] = storage.Host{HostID: "host-id", Hostname: "web-01"}

	evt := validEvent("host-id")
	evt.EventDetailJson = nil // empty → should store as "null"

	stream := newFakeStream(context.Background(), evt)
	_ = srv.StreamAlerts(stream)

	if len(store.insertedAlerts) != 1 {
		t.Fatalf("expected 1 alert, got %d", len(store.insertedAlerts))
	}
	if string(store.insertedAlerts[0].EventDetail) != "null" {
		t.Errorf("expected null event_detail, got %s", store.insertedAlerts[0].EventDetail)
	}
}
