package websocket_test

import (
	"encoding/json"
	"log/slog"
	"os"
	"testing"
	"time"

	ws "github.com/tripwire/agent/internal/server/websocket"
)

func newTestBroadcaster() *ws.Broadcaster {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	return ws.NewBroadcaster(logger, 16)
}

// TestBroadcasterRegisterUnregister verifies that Register/Unregister work and
// that ClientCount tracks the number of connected clients.
func TestBroadcasterRegisterUnregister(t *testing.T) {
	t.Parallel()

	bc := newTestBroadcaster()

	if got := bc.ClientCount(); got != 0 {
		t.Fatalf("expected 0 clients after init, got %d", got)
	}

	c1 := bc.Register("c1")
	c2 := bc.Register("c2")

	if got := bc.ClientCount(); got != 2 {
		t.Fatalf("expected 2 clients, got %d", got)
	}

	if c1.ID() != "c1" {
		t.Errorf("client ID mismatch: got %q, want %q", c1.ID(), "c1")
	}

	bc.Unregister("c1")
	if got := bc.ClientCount(); got != 1 {
		t.Fatalf("expected 1 client after unregister, got %d", got)
	}

	// Send channel should be closed after unregister.
	select {
	case _, ok := <-c1.Send():
		if ok {
			t.Error("expected send channel to be closed after Unregister")
		}
	default:
		t.Error("expected send channel to be closed (readable), not blocked")
	}

	bc.Unregister("c2")
	_ = c2
	if got := bc.ClientCount(); got != 0 {
		t.Fatalf("expected 0 clients, got %d", got)
	}
}

// TestBroadcasterBroadcast verifies that Broadcast delivers the message to all
// registered clients with correct JSON structure.
func TestBroadcasterBroadcast(t *testing.T) {
	t.Parallel()

	bc := newTestBroadcaster()

	c1 := bc.Register("c1")
	c2 := bc.Register("c2")
	defer bc.Unregister("c1")
	defer bc.Unregister("c2")

	msg := ws.AlertMessage{
		Type: "alert",
		Data: ws.AlertData{
			AlertID:      "alert-uuid",
			HostID:       "host-uuid",
			Hostname:     "web-01",
			Timestamp:    "2026-02-26T10:00:00Z",
			TripwireType: "FILE",
			RuleName:     "etc-passwd-watch",
			Severity:     "CRITICAL",
		},
	}

	bc.Broadcast(msg)

	// Both clients should receive the message within a short timeout.
	deadline := time.After(100 * time.Millisecond)
	for _, ch := range []<-chan []byte{c1.Send(), c2.Send()} {
		select {
		case raw, ok := <-ch:
			if !ok {
				t.Fatal("send channel closed unexpectedly")
			}
			var got ws.AlertMessage
			if err := json.Unmarshal(raw, &got); err != nil {
				t.Fatalf("unmarshal: %v", err)
			}
			if got.Type != "alert" {
				t.Errorf("got type %q, want %q", got.Type, "alert")
			}
			if got.Data.AlertID != "alert-uuid" {
				t.Errorf("got alert_id %q, want %q", got.Data.AlertID, "alert-uuid")
			}
			if got.Data.Severity != "CRITICAL" {
				t.Errorf("got severity %q, want %q", got.Data.Severity, "CRITICAL")
			}
		case <-deadline:
			t.Fatal("timeout waiting for broadcast message")
		}
	}
}

// TestBroadcasterDropsWhenBufferFull verifies that a slow client's send buffer
// fills up and subsequent messages are dropped (Dropped counter is incremented).
func TestBroadcasterDropsWhenBufferFull(t *testing.T) {
	t.Parallel()

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	bc := ws.NewBroadcaster(logger, 2) // tiny buffer

	c := bc.Register("slow-client")
	defer bc.Unregister("slow-client")

	msg := ws.AlertMessage{Type: "alert", Data: ws.AlertData{AlertID: "x"}}

	// Fill the buffer (2 slots).
	bc.Broadcast(msg)
	bc.Broadcast(msg)

	// This one should be dropped.
	bc.Broadcast(msg)

	if got := c.Dropped.Load(); got < 1 {
		t.Errorf("expected at least 1 drop, got %d", got)
	}
}

// TestBroadcasterUnregisterNonexistent verifies that unregistering an unknown
// client ID is a no-op and does not panic.
func TestBroadcasterUnregisterNonexistent(t *testing.T) {
	t.Parallel()

	bc := newTestBroadcaster()
	// Should not panic.
	bc.Unregister("does-not-exist")
}

// TestBroadcastEmptyRoom verifies that broadcasting with no clients registered
// does not panic or block.
func TestBroadcastEmptyRoom(t *testing.T) {
	t.Parallel()

	bc := newTestBroadcaster()
	// Should not panic or block.
	bc.Broadcast(ws.AlertMessage{Type: "alert", Data: ws.AlertData{AlertID: "x"}})
}
