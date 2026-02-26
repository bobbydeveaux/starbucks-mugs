package queue_test

import (
	"context"
	"fmt"
	"path/filepath"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/queue"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// makeEvent returns a minimal AlertEvent for use in tests.
func makeEvent(tripwireType, ruleName, severity string) agent.AlertEvent {
	return agent.AlertEvent{
		TripwireType: tripwireType,
		RuleName:     ruleName,
		Severity:     severity,
		Timestamp:    time.Now().UTC().Truncate(time.Millisecond),
		Detail:       map[string]any{"path": "/etc/passwd", "uid": 0},
	}
}

// openMemQueue opens an in-memory SQLiteQueue and registers t.Cleanup to
// close it, ensuring the database is closed even when tests fail.
func openMemQueue(t *testing.T) *queue.SQLiteQueue {
	t.Helper()
	q, err := queue.New(":memory:")
	if err != nil {
		t.Fatalf("queue.New(:memory:): %v", err)
	}
	t.Cleanup(func() { _ = q.Close() })
	return q
}

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

func TestNew_InMemory_EmptyDepth(t *testing.T) {
	q := openMemQueue(t)
	if d := q.Depth(); d != 0 {
		t.Errorf("Depth = %d after open, want 0", d)
	}
}

func TestNew_FileDB_CreatesFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "queue.db")

	q, err := queue.New(path)
	if err != nil {
		t.Fatalf("queue.New(%q): %v", path, err)
	}
	_ = q.Close()
}

// ---------------------------------------------------------------------------
// Enqueue
// ---------------------------------------------------------------------------

func TestEnqueue_IncreasesDepth(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	evt := makeEvent("FILE", "etc-passwd-watch", "CRITICAL")
	if err := q.Enqueue(ctx, evt); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}

	if d := q.Depth(); d != 1 {
		t.Errorf("Depth = %d after one Enqueue, want 1", d)
	}
}

func TestEnqueue_MultipleEvents_DepthAccumulates(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		if err := q.Enqueue(ctx, makeEvent("FILE", fmt.Sprintf("rule-%d", i), "INFO")); err != nil {
			t.Fatalf("Enqueue %d: %v", i, err)
		}
	}

	if d := q.Depth(); d != 5 {
		t.Errorf("Depth = %d after 5 enqueues, want 5", d)
	}
}

// ---------------------------------------------------------------------------
// Dequeue
// ---------------------------------------------------------------------------

func TestDequeue_ReturnsEventsInInsertionOrder(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	evts := []agent.AlertEvent{
		makeEvent("FILE", "rule-1", "INFO"),
		makeEvent("NETWORK", "rule-2", "WARN"),
		makeEvent("PROCESS", "rule-3", "CRITICAL"),
	}
	for _, e := range evts {
		if err := q.Enqueue(ctx, e); err != nil {
			t.Fatalf("Enqueue: %v", err)
		}
	}

	pending, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(pending) != 3 {
		t.Fatalf("Dequeue returned %d events, want 3", len(pending))
	}

	for i, pe := range pending {
		if pe.Evt.RuleName != evts[i].RuleName {
			t.Errorf("event[%d].RuleName = %q, want %q", i, pe.Evt.RuleName, evts[i].RuleName)
		}
		if pe.Evt.TripwireType != evts[i].TripwireType {
			t.Errorf("event[%d].TripwireType = %q, want %q", i, pe.Evt.TripwireType, evts[i].TripwireType)
		}
		if pe.Evt.Severity != evts[i].Severity {
			t.Errorf("event[%d].Severity = %q, want %q", i, pe.Evt.Severity, evts[i].Severity)
		}
	}
}

func TestDequeue_RespectsLimit(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	for i := 0; i < 10; i++ {
		_ = q.Enqueue(ctx, makeEvent("FILE", fmt.Sprintf("rule-%d", i), "INFO"))
	}

	pending, err := q.Dequeue(ctx, 4)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(pending) != 4 {
		t.Errorf("Dequeue returned %d events, want 4", len(pending))
	}
}

func TestDequeue_ZeroLimit_ReturnsNil(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()
	_ = q.Enqueue(ctx, makeEvent("FILE", "r", "INFO"))

	pending, err := q.Dequeue(ctx, 0)
	if err != nil {
		t.Fatalf("Dequeue(0): %v", err)
	}
	if len(pending) != 0 {
		t.Errorf("Dequeue(0) returned %d events, want 0", len(pending))
	}
}

func TestDequeue_PreservesTimestamp(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	// Use a rounded timestamp so nanosecond precision does not cause spurious
	// mismatches on systems where time.Now() has sub-millisecond resolution.
	orig := time.Now().UTC().Round(time.Millisecond)

	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     "ts-test",
		Severity:     "INFO",
		Timestamp:    orig,
		Detail:       map[string]any{},
	}
	_ = q.Enqueue(ctx, evt)

	pending, err := q.Dequeue(ctx, 1)
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if len(pending) != 1 {
		t.Fatalf("Dequeue returned %d events, want 1", len(pending))
	}
	if !pending[0].Evt.Timestamp.Equal(orig) {
		t.Errorf("Timestamp = %v, want %v", pending[0].Evt.Timestamp, orig)
	}
}

// ---------------------------------------------------------------------------
// Ack
// ---------------------------------------------------------------------------

func TestAck_MarksEventDelivered(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	_ = q.Enqueue(ctx, makeEvent("FILE", "rule-1", "INFO"))

	pending, err := q.Dequeue(ctx, 10)
	if err != nil || len(pending) != 1 {
		t.Fatalf("Dequeue: err=%v, got %d events", err, len(pending))
	}

	if err := q.Ack(ctx, []int64{pending[0].ID}); err != nil {
		t.Fatalf("Ack: %v", err)
	}

	// Depth should reach zero.
	if d := q.Depth(); d != 0 {
		t.Errorf("Depth = %d after Ack, want 0", d)
	}

	// A subsequent Dequeue should return nothing.
	pending2, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("second Dequeue: %v", err)
	}
	if len(pending2) != 0 {
		t.Errorf("second Dequeue returned %d events after Ack, want 0", len(pending2))
	}
}

func TestAck_Idempotent(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	_ = q.Enqueue(ctx, makeEvent("FILE", "r", "INFO"))
	pending, _ := q.Dequeue(ctx, 1)

	// Ack twice — must not return an error or corrupt the depth counter.
	if err := q.Ack(ctx, []int64{pending[0].ID}); err != nil {
		t.Fatalf("first Ack: %v", err)
	}
	if err := q.Ack(ctx, []int64{pending[0].ID}); err != nil {
		t.Fatalf("second (duplicate) Ack: %v", err)
	}

	if d := q.Depth(); d != 0 {
		t.Errorf("Depth = %d after duplicate Ack, want 0", d)
	}
}

func TestAck_EmptyIDs_IsNoop(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	if err := q.Ack(ctx, nil); err != nil {
		t.Errorf("Ack(nil): unexpected error: %v", err)
	}
	if err := q.Ack(ctx, []int64{}); err != nil {
		t.Errorf("Ack([]): unexpected error: %v", err)
	}
}

func TestAck_PartialAck_LeavesPendingEvents(t *testing.T) {
	q := openMemQueue(t)
	ctx := context.Background()

	for i := 0; i < 3; i++ {
		_ = q.Enqueue(ctx, makeEvent("FILE", fmt.Sprintf("rule-%d", i), "INFO"))
	}

	pending, _ := q.Dequeue(ctx, 10)
	if len(pending) != 3 {
		t.Fatalf("expected 3 pending events, got %d", len(pending))
	}

	// Ack only the first event.
	if err := q.Ack(ctx, []int64{pending[0].ID}); err != nil {
		t.Fatalf("Ack: %v", err)
	}

	if d := q.Depth(); d != 2 {
		t.Errorf("Depth = %d after partial Ack, want 2", d)
	}

	remaining, err := q.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue after partial Ack: %v", err)
	}
	if len(remaining) != 2 {
		t.Errorf("Dequeue returned %d events, want 2", len(remaining))
	}
}

// ---------------------------------------------------------------------------
// Crash recovery
// ---------------------------------------------------------------------------

func TestCrashRecovery_UnacknowledgedEventsRedelivered(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "queue.db")
	ctx := context.Background()

	// Phase 1 — enqueue two events; ack only the first (simulating a crash
	// that occurs before the second event is acknowledged).
	func() {
		q, err := queue.New(dbPath)
		if err != nil {
			t.Fatalf("open 1: %v", err)
		}
		defer q.Close()

		_ = q.Enqueue(ctx, makeEvent("FILE", "acked-rule", "INFO"))
		_ = q.Enqueue(ctx, makeEvent("NETWORK", "pending-rule", "WARN"))

		pending, err := q.Dequeue(ctx, 10)
		if err != nil || len(pending) != 2 {
			t.Fatalf("phase 1 Dequeue: err=%v, got %d events", err, len(pending))
		}
		// Ack only the first.
		_ = q.Ack(ctx, []int64{pending[0].ID})
	}()

	// Phase 2 — reopen the database (simulating a restart after the crash).
	q2, err := queue.New(dbPath)
	if err != nil {
		t.Fatalf("open 2: %v", err)
	}
	defer q2.Close()

	if d := q2.Depth(); d != 1 {
		t.Errorf("after restart Depth = %d, want 1 (one unacknowledged event)", d)
	}

	pending, err := q2.Dequeue(ctx, 10)
	if err != nil {
		t.Fatalf("Dequeue after restart: %v", err)
	}
	if len(pending) != 1 {
		t.Fatalf("after restart got %d events, want 1", len(pending))
	}
	if pending[0].Evt.RuleName != "pending-rule" {
		t.Errorf("RuleName = %q, want %q", pending[0].Evt.RuleName, "pending-rule")
	}
}

func TestCrashRecovery_AllAcked_EmptyOnRestart(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "queue.db")
	ctx := context.Background()

	func() {
		q, err := queue.New(dbPath)
		if err != nil {
			t.Fatalf("open 1: %v", err)
		}
		defer q.Close()

		_ = q.Enqueue(ctx, makeEvent("FILE", "r1", "INFO"))
		_ = q.Enqueue(ctx, makeEvent("FILE", "r2", "WARN"))

		pending, _ := q.Dequeue(ctx, 10)
		ids := make([]int64, len(pending))
		for i, pe := range pending {
			ids[i] = pe.ID
		}
		_ = q.Ack(ctx, ids)
	}()

	q2, err := queue.New(dbPath)
	if err != nil {
		t.Fatalf("open 2: %v", err)
	}
	defer q2.Close()

	if d := q2.Depth(); d != 0 {
		t.Errorf("after restart Depth = %d, want 0 (all acked)", d)
	}
}

// ---------------------------------------------------------------------------
// Interface compliance
// ---------------------------------------------------------------------------

// TestSQLiteQueue_ImplementsQueueInterface verifies at compile time that
// *SQLiteQueue satisfies the agent.Queue interface.
func TestSQLiteQueue_ImplementsQueueInterface(t *testing.T) {
	var _ agent.Queue = (*queue.SQLiteQueue)(nil)
}
