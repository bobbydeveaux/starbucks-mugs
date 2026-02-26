// Package queue provides a WAL-mode SQLite-backed alert queue for the
// TripWire agent. It implements the agent.Queue interface and adds Dequeue
// and Ack operations to support at-least-once delivery semantics: events are
// persisted on Enqueue and are not removed until the caller calls Ack.
//
// # WAL mode
//
// The database is opened with PRAGMA journal_mode = WAL so that concurrent
// readers and a single writer can proceed without blocking each other. This
// is important because the agent's event-processing goroutines call Enqueue
// while a separate delivery goroutine calls Dequeue and Ack.
//
// # At-least-once delivery
//
// The delivered column is set to 1 only when Ack is called. If the process
// crashes between Enqueue and Ack, the event is returned again by the next
// Dequeue call after restart, ensuring every alert reaches the dashboard even
// when the transport is temporarily unavailable.
package queue

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"
	"sync/atomic"
	"time"

	"github.com/tripwire/agent/internal/agent"
	_ "modernc.org/sqlite" // register "sqlite" driver with database/sql
)

// SQLiteQueue is a WAL-mode SQLite-backed implementation of agent.Queue.
// It is safe for concurrent use.
type SQLiteQueue struct {
	db    *sql.DB
	depth atomic.Int64
}

// New opens (or creates) the SQLite database at path, enables WAL journal
// mode, and applies the schema. If path is ":memory:", an in-memory database
// is used; this is suitable for tests but loses all data when closed.
//
// New seeds the internal depth counter from the number of rows currently
// marked as pending (delivered = 0), so Depth() is accurate immediately
// after a crash-recovery restart.
func New(path string) (*SQLiteQueue, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("queue: open %q: %w", path, err)
	}

	// SQLite allows only one writer at a time. Limiting the pool to a single
	// connection avoids "database is locked" errors when multiple goroutines
	// call Enqueue concurrently; each call serialises through this connection.
	db.SetMaxOpenConns(1)

	// Enable WAL mode: readers and the single writer proceed concurrently.
	if _, err := db.Exec(`PRAGMA journal_mode = WAL`); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("queue: set WAL mode: %w", err)
	}

	// NORMAL synchronous: durable across application crashes; not OS crashes.
	// This gives a significant write-throughput improvement over FULL while
	// still guaranteeing that a committed transaction survives a process exit.
	if _, err := db.Exec(`PRAGMA synchronous = NORMAL`); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("queue: set synchronous = NORMAL: %w", err)
	}

	// Apply the schema (idempotent: CREATE TABLE IF NOT EXISTS).
	if _, err := db.Exec(ddl); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("queue: apply schema: %w", err)
	}

	q := &SQLiteQueue{db: db}

	// Seed the depth counter from existing undelivered rows so that Depth()
	// reflects the correct value immediately after a restart.
	var count int64
	if err := db.QueryRow(`SELECT COUNT(*) FROM alert_queue WHERE delivered = 0`).Scan(&count); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("queue: count pending rows: %w", err)
	}
	q.depth.Store(count)

	return q, nil
}

// ddl is the schema DDL, kept here to keep the package self-contained.
// It mirrors the canonical schema.sql file in this directory.
const ddl = `
CREATE TABLE IF NOT EXISTS alert_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tripwire_type TEXT    NOT NULL,
    rule_name     TEXT    NOT NULL,
    severity      TEXT    NOT NULL,
    ts            TEXT    NOT NULL,
    detail        TEXT    NOT NULL DEFAULT '{}',
    enqueued_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alert_queue_pending
    ON alert_queue (delivered, id);
`

// Enqueue persists evt to the SQLite database. It implements agent.Queue.
// The event is stored with delivered = 0 and is included in subsequent
// Dequeue results until Ack is called for its ID.
func (q *SQLiteQueue) Enqueue(ctx context.Context, evt agent.AlertEvent) error {
	detail, err := json.Marshal(evt.Detail)
	if err != nil {
		return fmt.Errorf("queue: marshal detail: %w", err)
	}

	_, err = q.db.ExecContext(ctx,
		`INSERT INTO alert_queue (tripwire_type, rule_name, severity, ts, detail)
		 VALUES (?, ?, ?, ?, ?)`,
		evt.TripwireType,
		evt.RuleName,
		evt.Severity,
		evt.Timestamp.UTC().Format(time.RFC3339Nano),
		string(detail),
	)
	if err != nil {
		return fmt.Errorf("queue: enqueue: %w", err)
	}

	q.depth.Add(1)
	return nil
}

// PendingEvent is an unacknowledged alert event returned by Dequeue.
// ID is the database primary key used to acknowledge the event via Ack.
type PendingEvent struct {
	ID  int64
	Evt agent.AlertEvent
}

// Dequeue returns up to n unacknowledged events in insertion order (oldest
// first). It does not mark events as delivered; call Ack with the returned
// IDs to do that. If n ≤ 0, Dequeue returns nil without querying the database.
func (q *SQLiteQueue) Dequeue(ctx context.Context, n int) ([]PendingEvent, error) {
	if n <= 0 {
		return nil, nil
	}

	rows, err := q.db.QueryContext(ctx,
		`SELECT id, tripwire_type, rule_name, severity, ts, detail
		 FROM   alert_queue
		 WHERE  delivered = 0
		 ORDER  BY id
		 LIMIT  ?`, n)
	if err != nil {
		return nil, fmt.Errorf("queue: dequeue query: %w", err)
	}
	defer rows.Close()

	var events []PendingEvent
	for rows.Next() {
		var (
			pe        PendingEvent
			tsStr     string
			detailStr string
		)
		if err := rows.Scan(
			&pe.ID,
			&pe.Evt.TripwireType,
			&pe.Evt.RuleName,
			&pe.Evt.Severity,
			&tsStr,
			&detailStr,
		); err != nil {
			return nil, fmt.Errorf("queue: dequeue scan: %w", err)
		}

		// Parse the stored RFC3339Nano timestamp; fall back to RFC3339.
		pe.Evt.Timestamp, err = time.Parse(time.RFC3339Nano, tsStr)
		if err != nil {
			pe.Evt.Timestamp, _ = time.Parse(time.RFC3339, tsStr)
		}

		// Unmarshal the detail JSON; a malformed value produces a nil map
		// rather than an error so that one bad row does not block the queue.
		if err := json.Unmarshal([]byte(detailStr), &pe.Evt.Detail); err != nil {
			pe.Evt.Detail = nil
		}

		events = append(events, pe)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("queue: dequeue rows: %w", err)
	}
	return events, nil
}

// Ack marks the events identified by ids as delivered. Acknowledged events
// are excluded from subsequent Dequeue results. Ack is idempotent: calling
// it multiple times with the same IDs is safe.
//
// The depth counter is decremented by the number of rows whose delivered
// column transitions from 0 to 1 (already-acked IDs are skipped).
func (q *SQLiteQueue) Ack(ctx context.Context, ids []int64) error {
	if len(ids) == 0 {
		return nil
	}

	placeholders := strings.Repeat("?,", len(ids))
	placeholders = placeholders[:len(placeholders)-1] // trim trailing comma

	args := make([]any, len(ids))
	for i, id := range ids {
		args[i] = id
	}

	result, err := q.db.ExecContext(ctx,
		fmt.Sprintf(`UPDATE alert_queue SET delivered = 1 WHERE id IN (%s) AND delivered = 0`, placeholders),
		args...,
	)
	if err != nil {
		return fmt.Errorf("queue: ack: %w", err)
	}

	n, _ := result.RowsAffected()
	q.depth.Add(-n)
	return nil
}

// Depth returns the number of pending (unacknowledged) events. It reads from
// an atomic counter that is updated by Enqueue and Ack, so it never blocks.
// It implements agent.Queue.
func (q *SQLiteQueue) Depth() int {
	return int(q.depth.Load())
}

// Close closes the underlying database connection. It implements agent.Queue.
// Subsequent calls to any method are undefined; callers must not use the
// queue after Close returns.
func (q *SQLiteQueue) Close() error {
	return q.db.Close()
}
