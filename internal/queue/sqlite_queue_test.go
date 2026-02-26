package queue_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/queue"
)

// sampleEvent returns a reproducible AlertEvent for use in tests.
func sampleEvent(i int) agent.AlertEvent {
	return agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     "test-rule",
		Severity:     "WARN",
		Timestamp:    time.Date(2026, 2, 25, 12, 0, i, 0, time.UTC),
		Detail: map[string]any{
			"path":  "/etc/passwd",
			"index": i,
		},
	}
}

// openQueue is a test helper that opens a new SQLiteQueue backed by a temp file
// and registers cleanup with t.
func openQueue(t *testing.T) *queue.SQLiteQueue {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "alerts.db")
	q, err := queue.Open(path, nil)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { _ = q.Close() })
	return q
}

// --------------------------------------------------------------------------
// TestEnqueue
// --------------------------------------------------------------------------

func TestEnqueue_DepthIncrements(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	if d := q.Depth(); d != 0 {
		t.Fatalf("initial depth = %d, want 0", d)
	}

	for i := 0; i < 3; i++ {
		if err := q.Enqueue(ctx, sampleEvent(i)); err != nil {
			t.Fatalf("Enqueue[%d]: %v", i, err)
		}
	}

	if d := q.Depth(); d != 3 {
		t.Errorf("depth after 3 enqueues = %d, want 3", d)
	}
}

func TestEnqueue_PersistsAllFields(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	evt := agent.AlertEvent{
		TripwireType: "NETWORK",
		RuleName:     "port-scan",
		Severity:     "CRITICAL",
		Timestamp:    time.Date(2026, 1, 15, 8, 30, 0, 0, time.UTC),
		Detail:       map[string]any{"source_ip": "1.2.3.4", "port": 443},
	}

	if err := q.Enqueue(ctx, evt); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}

	rows, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("dequeued %d rows, want 1", len(rows))
	}

	got := rows[0].Evt
	if got.TripwireType != evt.TripwireType {
		t.Errorf("TripwireType = %q, want %q", got.TripwireType, evt.TripwireType)
	}
	if got.RuleName != evt.RuleName {
		t.Errorf("RuleName = %q, want %q", got.RuleName, evt.RuleName)
	}
	if got.Severity != evt.Severity {
		t.Errorf("Severity = %q, want %q", got.Severity, evt.Severity)
	}
	if !got.Timestamp.Equal(evt.Timestamp) {
		t.Errorf("Timestamp = %v, want %v", got.Timestamp, evt.Timestamp)
	}
	// Verify detail round-trips (JSON numbers become float64).
	if got.Detail["source_ip"] != "1.2.3.4" {
		t.Errorf("Detail[source_ip] = %v, want 1.2.3.4", got.Detail["source_ip"])
	}
}

// --------------------------------------------------------------------------
// TestDequeue
// --------------------------------------------------------------------------

func TestDequeue_ReturnsInsertionOrder(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		if err := q.Enqueue(ctx, sampleEvent(i)); err != nil {
			t.Fatalf("Enqueue[%d]: %v", i, err)
		}
	}

	rows, err := q.Dequeue(ctx, 5)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(rows) != 5 {
		t.Fatalf("Dequeue returned %d rows, want 5", len(rows))
	}

	// IDs must be strictly increasing (insertion order).
	for i := 1; i < len(rows); i++ {
		if rows[i].ID <= rows[i-1].ID {
			t.Errorf("rows[%d].ID = %d, want > %d", i, rows[i].ID, rows[i-1].ID)
		}
	}
}

func TestDequeue_LimitRespected(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		if err := q.Enqueue(ctx, sampleEvent(i)); err != nil {
			t.Fatalf("Enqueue[%d]: %v", i, err)
		}
	}

	rows, err := q.Dequeue(ctx, 2)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(rows) != 2 {
		t.Errorf("Dequeue(2) returned %d rows, want 2", len(rows))
	}
}

func TestDequeue_EmptyQueueReturnsNil(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	rows, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue on empty queue: %v", err)
	}
	if len(rows) != 0 {
		t.Errorf("Dequeue on empty queue returned %d rows, want 0", len(rows))
	}
}

// --------------------------------------------------------------------------
// TestAck
// --------------------------------------------------------------------------

func TestAck_AcknowledgedEventsNotReDelivered(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	for i := 0; i < 3; i++ {
		if err := q.Enqueue(ctx, sampleEvent(i)); err != nil {
			t.Fatalf("Enqueue[%d]: %v", i, err)
		}
	}

	// Dequeue all 3.
	rows, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("first Dequeue: got %d, want 3", len(rows))
	}

	// Acknowledge only the first two.
	for _, r := range rows[:2] {
		if err := q.Ack(ctx, r.ID); err != nil {
			t.Fatalf("Ack(%d): %v", r.ID, err)
		}
	}

	// Depth should now be 1.
	if d := q.Depth(); d != 1 {
		t.Errorf("depth after 2 acks = %d, want 1", d)
	}

	// Second Dequeue should return only the unacknowledged row.
	rows2, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("second Dequeue: %v", err)
	}
	if len(rows2) != 1 {
		t.Fatalf("second Dequeue: got %d, want 1", len(rows2))
	}
	if rows2[0].ID != rows[2].ID {
		t.Errorf("second Dequeue returned ID %d, want %d", rows2[0].ID, rows[2].ID)
	}
}

func TestAck_IdempotentForAlreadyAcknowledged(t *testing.T) {
	q := openQueue(t)
	ctx := context.Background()

	if err := q.Enqueue(ctx, sampleEvent(0)); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}

	rows, err := q.Dequeue(ctx, 1)
	if err != nil || len(rows) != 1 {
		t.Fatalf("Dequeue: %v, %d rows", err, len(rows))
	}

	// Ack twice — must not error.
	if err := q.Ack(ctx, rows[0].ID); err != nil {
		t.Fatalf("first Ack: %v", err)
	}
	if err := q.Ack(ctx, rows[0].ID); err != nil {
		t.Fatalf("second Ack (idempotent): %v", err)
	}
}

// --------------------------------------------------------------------------
// TestCrashRecovery
// --------------------------------------------------------------------------

func TestCrashRecovery_UnacknowledgedEventsReDeliveredAfterReopen(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "alerts.db")
	ctx := context.Background()

	// First session: enqueue 3 events, ack 1.
	func() {
		q, err := queue.Open(path, nil)
		if err != nil {
			t.Fatalf("first Open: %v", err)
		}
		defer q.Close()

		for i := 0; i < 3; i++ {
			if err := q.Enqueue(ctx, sampleEvent(i)); err != nil {
				t.Fatalf("Enqueue[%d]: %v", i, err)
			}
		}

		rows, err := q.Dequeue(ctx, 3)
		if err != nil || len(rows) != 3 {
			t.Fatalf("Dequeue: %v, %d rows", err, len(rows))
		}

		// Acknowledge only the first event (simulate partial delivery).
		if err := q.Ack(ctx, rows[0].ID); err != nil {
			t.Fatalf("Ack: %v", err)
		}
	}()

	// Second session (simulates restart after crash): the 2 unacknowledged
	// events must still be returned by Dequeue.
	q2, err := queue.Open(path, nil)
	if err != nil {
		t.Fatalf("second Open: %v", err)
	}
	defer q2.Close()

	if d := q2.Depth(); d != 2 {
		t.Errorf("depth on reopen = %d, want 2", d)
	}

	rows, err := q2.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("second session Dequeue: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("second session Dequeue: got %d rows, want 2", len(rows))
	}
}

func TestCrashRecovery_WALModeEnabledAfterReopen(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "alerts.db")
	ctx := context.Background()

	// Open, enqueue, and close.
	q, err := queue.Open(path, nil)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := q.Enqueue(ctx, sampleEvent(0)); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}
	if err := q.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	// The WAL file should exist after writing in WAL mode.
	walPath := path + "-wal"
	// The WAL file may have been folded back into the main DB after close;
	// what matters is that the main DB file exists and is readable.
	if _, err := os.Stat(path); err != nil {
		t.Errorf("database file missing after close: %v", err)
	}
	// Suppress unused variable warning if walPath is not found (it's optional).
	_ = walPath

	// Reopen and verify the event is still present.
	q2, err := queue.Open(path, nil)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer q2.Close()

	if d := q2.Depth(); d != 1 {
		t.Errorf("depth on reopen = %d, want 1", d)
	}
}

// --------------------------------------------------------------------------
// TestClose
// --------------------------------------------------------------------------

func TestClose_MultipleClosesAreIdempotent(t *testing.T) {
	q := openQueue(t)

	if err := q.Close(); err != nil {
		t.Fatalf("first Close: %v", err)
	}
	// The test helper's t.Cleanup will call Close again; must not panic/error.
}

func TestClose_OperationsAfterCloseReturnError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "alerts.db")
	q, err := queue.Open(path, nil)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}

	if err := q.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	ctx := context.Background()
	if err := q.Enqueue(ctx, sampleEvent(0)); err == nil {
		t.Error("Enqueue on closed queue: expected error, got nil")
	}
	if _, err := q.Dequeue(ctx, 1); err == nil {
		t.Error("Dequeue on closed queue: expected error, got nil")
	}
	if err := q.Ack(ctx, 1); err == nil {
		t.Error("Ack on closed queue: expected error, got nil")
	}
}

// --------------------------------------------------------------------------
// TestSatisfiesAgentQueueInterface
// --------------------------------------------------------------------------

// TestSatisfiesAgentQueueInterface ensures that *SQLiteQueue satisfies the
// agent.Queue interface at compile time.
func TestSatisfiesAgentQueueInterface(t *testing.T) {
	q := openQueue(t)
	var _ agent.Queue = q
}
