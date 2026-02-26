// Package queue provides a durable, WAL-mode SQLite-backed alert queue that
// satisfies the agent.Queue interface.  The queue is used by the TripWire
// agent to buffer alert events locally when the dashboard transport is
// unavailable, implementing at-least-once delivery semantics.
//
// # WAL mode
//
// The SQLite database is opened with journal_mode=WAL and synchronous=NORMAL,
// which allows concurrent reads alongside the single writer and provides good
// throughput for the agent's insert-heavy workload.  WAL mode also makes
// crash recovery safer: an incomplete transaction is simply rolled back from
// the WAL file on the next open.
//
// # At-least-once delivery
//
// Events are persisted by Enqueue and remain in the database with
// delivered=0 until the caller explicitly acknowledges them via Ack.
// Acknowledged events are marked delivered=1 but never physically deleted,
// providing a complete local audit trail.  On restart, the transport layer
// calls Dequeue and Ack again for any events that were not acknowledged before
// the previous shutdown.
//
// # Thread safety
//
// SQLiteQueue is safe for concurrent use from multiple goroutines.  A single
// *sql.DB handle is used; database/sql manages a connection pool internally.
// SQLite's WAL mode allows concurrent readers, and database/sql serialises
// writers automatically.
package queue

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"time"

	_ "modernc.org/sqlite" // register the "sqlite" driver with database/sql

	"github.com/tripwire/agent/internal/agent"
)

// driverName is the name under which modernc.org/sqlite registers itself with
// the database/sql package.
const driverName = "sqlite"

// SQLiteQueue is a WAL-mode SQLite-backed implementation of agent.Queue.
// Create one with Open; do not copy after first use.
type SQLiteQueue struct {
	db     *sql.DB
	logger *slog.Logger

	mu     sync.Mutex
	closed bool
}

// Row is a single queued alert together with its database row ID.  The ID is
// needed to acknowledge the event via Ack after successful delivery.
type Row struct {
	ID  int64
	Evt agent.AlertEvent
}

// Open opens (or creates) the SQLite database at path, enables WAL journal
// mode, and applies the schema from schema.sql (embedded at compile time).  It
// returns an error if the database cannot be opened or the schema cannot be
// applied.
func Open(path string, logger *slog.Logger) (*SQLiteQueue, error) {
	if logger == nil {
		logger = slog.Default()
	}

	// Use the file path with no extra query parameters; pragmas are set
	// programmatically below so they can be verified and logged.
	db, err := sql.Open(driverName, path)
	if err != nil {
		return nil, fmt.Errorf("queue: open sqlite %q: %w", path, err)
	}

	// Limit to a single connection so that PRAGMA journal_mode=WAL takes
	// effect globally and we avoid "database is locked" errors from
	// concurrent writers on WAL mode setup.
	db.SetMaxOpenConns(1)

	if err := applySchema(db); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("queue: apply schema: %w", err)
	}

	q := &SQLiteQueue{
		db:     db,
		logger: logger,
	}

	logger.Info("alert queue opened", slog.String("path", path))
	return q, nil
}

// applySchema executes the WAL pragma and DDL statements needed to initialise
// (or verify) the database schema.
func applySchema(db *sql.DB) error {
	stmts := []string{
		`PRAGMA journal_mode=WAL`,
		`PRAGMA synchronous=NORMAL`,
		`CREATE TABLE IF NOT EXISTS alerts (
			id            INTEGER PRIMARY KEY AUTOINCREMENT,
			tripwire_type TEXT    NOT NULL,
			rule_name     TEXT    NOT NULL,
			severity      TEXT    NOT NULL,
			ts            TEXT    NOT NULL,
			detail        TEXT    NOT NULL DEFAULT '{}',
			delivered     INTEGER NOT NULL DEFAULT 0,
			created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
		)`,
		`CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts (delivered, id)`,
	}

	for _, stmt := range stmts {
		if _, err := db.Exec(stmt); err != nil {
			return fmt.Errorf("exec %q: %w", stmt[:min(len(stmt), 40)], err)
		}
	}
	return nil
}

// Enqueue persists evt in the database for at-least-once delivery.  It
// returns an error if the event cannot be serialised or written.  Enqueue is
// safe to call concurrently.
func (q *SQLiteQueue) Enqueue(ctx context.Context, evt agent.AlertEvent) error {
	q.mu.Lock()
	if q.closed {
		q.mu.Unlock()
		return fmt.Errorf("queue: enqueue on closed queue")
	}
	q.mu.Unlock()

	detail, err := json.Marshal(evt.Detail)
	if err != nil {
		return fmt.Errorf("queue: marshal detail: %w", err)
	}

	_, err = q.db.ExecContext(ctx,
		`INSERT INTO alerts (tripwire_type, rule_name, severity, ts, detail)
		 VALUES (?, ?, ?, ?, ?)`,
		evt.TripwireType,
		evt.RuleName,
		evt.Severity,
		evt.Timestamp.UTC().Format(time.RFC3339Nano),
		string(detail),
	)
	if err != nil {
		return fmt.Errorf("queue: insert alert: %w", err)
	}

	q.logger.Debug("alert enqueued",
		slog.String("type", evt.TripwireType),
		slog.String("rule", evt.RuleName),
	)
	return nil
}

// Dequeue returns up to n unacknowledged events in insertion order.  Callers
// should call Ack with each returned Row.ID after the event has been
// successfully delivered.  Dequeue never returns events that have already been
// acknowledged.
func (q *SQLiteQueue) Dequeue(ctx context.Context, n int) ([]Row, error) {
	q.mu.Lock()
	if q.closed {
		q.mu.Unlock()
		return nil, fmt.Errorf("queue: dequeue on closed queue")
	}
	q.mu.Unlock()

	if n <= 0 {
		return nil, nil
	}

	rows, err := q.db.QueryContext(ctx,
		`SELECT id, tripwire_type, rule_name, severity, ts, detail
		 FROM alerts
		 WHERE delivered = 0
		 ORDER BY id
		 LIMIT ?`,
		n,
	)
	if err != nil {
		return nil, fmt.Errorf("queue: dequeue query: %w", err)
	}
	defer rows.Close()

	var results []Row
	for rows.Next() {
		var (
			id           int64
			tripwireType string
			ruleName     string
			severity     string
			tsStr        string
			detailJSON   string
		)
		if err := rows.Scan(&id, &tripwireType, &ruleName, &severity, &tsStr, &detailJSON); err != nil {
			return nil, fmt.Errorf("queue: scan row: %w", err)
		}

		ts, err := time.Parse(time.RFC3339Nano, tsStr)
		if err != nil {
			// Fall back to zero time rather than failing the whole dequeue.
			q.logger.Warn("queue: failed to parse timestamp", slog.String("ts", tsStr), slog.Any("error", err))
			ts = time.Time{}
		}

		var detail map[string]any
		if err := json.Unmarshal([]byte(detailJSON), &detail); err != nil {
			q.logger.Warn("queue: failed to parse detail JSON", slog.Any("error", err))
			detail = map[string]any{}
		}

		results = append(results, Row{
			ID: id,
			Evt: agent.AlertEvent{
				TripwireType: tripwireType,
				RuleName:     ruleName,
				Severity:     severity,
				Timestamp:    ts,
				Detail:       detail,
			},
		})
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("queue: iterating rows: %w", err)
	}

	return results, nil
}

// Ack marks the event identified by id as delivered so it is not re-delivered
// on the next Dequeue call.  If id does not exist or has already been
// acknowledged, Ack returns without error (idempotent).
func (q *SQLiteQueue) Ack(ctx context.Context, id int64) error {
	q.mu.Lock()
	if q.closed {
		q.mu.Unlock()
		return fmt.Errorf("queue: ack on closed queue")
	}
	q.mu.Unlock()

	_, err := q.db.ExecContext(ctx,
		`UPDATE alerts SET delivered = 1 WHERE id = ?`,
		id,
	)
	if err != nil {
		return fmt.Errorf("queue: ack id %d: %w", id, err)
	}

	q.logger.Debug("alert acknowledged", slog.Int64("id", id))
	return nil
}

// Depth returns the number of pending (unacknowledged) events currently stored
// in the queue.  It queries the database directly so the count is always
// accurate.  Returns 0 if the queue is closed or the query fails.
func (q *SQLiteQueue) Depth() int {
	q.mu.Lock()
	if q.closed {
		q.mu.Unlock()
		return 0
	}
	q.mu.Unlock()

	var n int
	if err := q.db.QueryRow(`SELECT COUNT(*) FROM alerts WHERE delivered = 0`).Scan(&n); err != nil {
		q.logger.Warn("queue: depth query failed", slog.Any("error", err))
		return 0
	}
	return n
}

// Close flushes any pending operations and releases the database connection.
// It is safe to call Close multiple times; subsequent calls are no-ops.
func (q *SQLiteQueue) Close() error {
	q.mu.Lock()
	defer q.mu.Unlock()

	if q.closed {
		return nil
	}
	q.closed = true

	if err := q.db.Close(); err != nil {
		return fmt.Errorf("queue: close: %w", err)
	}

	q.logger.Info("alert queue closed")
	return nil
}

// min returns the smaller of a and b.  Replaces the built-in min from Go 1.21+
// to stay compatible with the module's go 1.22 directive.
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
