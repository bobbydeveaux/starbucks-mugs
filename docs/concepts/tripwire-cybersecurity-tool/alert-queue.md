# TripWire Agent — WAL-mode SQLite Alert Queue

This document describes the local alert queue implemented in
`internal/queue/sqlite_queue.go`.

---

## Overview

The alert queue provides durable, at-least-once delivery for `AlertEvent`
values emitted by watcher components.  It buffers events locally in a SQLite
database so that alerts are never lost when the dashboard transport is
temporarily unavailable (network outage, service restart, etc.).

The queue implements the `agent.Queue` interface and is wired into the agent
orchestrator via `WithQueue(q)`.

---

## Package: `internal/queue`

**Files:**
- `internal/queue/schema.sql` — DDL for the alerts table and supporting index
- `internal/queue/sqlite_queue.go` — queue implementation

### WAL journal mode

SQLite is opened with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`.

| Setting | Value | Rationale |
|---------|-------|-----------|
| `journal_mode` | `WAL` | Allows concurrent readers while a single writer inserts; significantly better throughput than `DELETE` (the default) for insert-heavy workloads |
| `synchronous` | `NORMAL` | Flushes at the most critical checkpoints only; provides good durability without the overhead of `FULL` mode |

WAL mode also makes crash recovery safer: an incomplete write transaction is
simply rolled back from the WAL file when the database is next opened.

### Schema

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tripwire_type TEXT    NOT NULL,          -- "FILE", "NETWORK", or "PROCESS"
    rule_name     TEXT    NOT NULL,
    severity      TEXT    NOT NULL,          -- "INFO", "WARN", or "CRITICAL"
    ts            TEXT    NOT NULL,          -- RFC3339Nano timestamp (UTC)
    detail        TEXT    NOT NULL DEFAULT '{}', -- JSON object
    delivered     INTEGER NOT NULL DEFAULT 0,    -- 0 = pending, 1 = acknowledged
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts (delivered, id);
```

Rows are **never physically deleted**; the `delivered` flag is set to `1`
after the transport layer acknowledges the event.  This preserves a complete
local history and makes re-delivery after a crash straightforward: on
re-open, any row with `delivered=0` is available from `Dequeue`.

### At-least-once delivery semantics

1. The agent calls `Enqueue` when a watcher emits an event.  The event is
   immediately written to the database.
2. The transport layer calls `Dequeue` to retrieve a batch of pending events.
3. After each event is successfully streamed to the dashboard, the transport
   calls `Ack` with the row `ID`.
4. If the agent crashes between `Enqueue` and `Ack`, the events remain in the
   database with `delivered=0` and are re-delivered after restart.

This design may deliver the same event more than once if a crash occurs after
the dashboard receives the event but before `Ack` is recorded locally.  The
dashboard de-duplicates using the event's timestamp and rule name.

---

## API

### `Open(path string, logger *slog.Logger) (*SQLiteQueue, error)`

Opens (or creates) the SQLite database at `path`, enables WAL mode, and
applies the schema.  Passing `nil` for `logger` uses `slog.Default()`.

```go
q, err := queue.Open("/var/lib/tripwire/alerts.db", logger)
if err != nil {
    log.Fatalf("queue: %v", err)
}
defer q.Close()
```

### `(*SQLiteQueue).Enqueue(ctx context.Context, evt agent.AlertEvent) error`

Persists `evt` in the database.  Returns an error if the queue is closed or
the insert fails.  Safe for concurrent use.

### `(*SQLiteQueue).Dequeue(ctx context.Context, n int) ([]Row, error)`

Returns up to `n` unacknowledged events in insertion order (ascending `id`).
The returned `Row` values carry both the database `ID` and the reconstructed
`AlertEvent`.  Only rows with `delivered=0` are returned; already-acknowledged
events are never re-delivered.

```go
rows, err := q.Dequeue(ctx, 50)
for _, r := range rows {
    if err := transport.Send(ctx, r.Evt); err != nil {
        break // retry on next poll
    }
    _ = q.Ack(ctx, r.ID)
}
```

### `(*SQLiteQueue).Ack(ctx context.Context, id int64) error`

Marks the event identified by `id` as delivered (`delivered=1`).  Idempotent:
calling `Ack` on an already-acknowledged row returns without error.

### `(*SQLiteQueue).Depth() int`

Returns the count of pending (unacknowledged) events by querying
`SELECT COUNT(*) FROM alerts WHERE delivered = 0`.  This value is surfaced by
the agent's `/healthz` endpoint as `queue_depth`.  Returns `0` if the queue is
closed or the query fails.

### `(*SQLiteQueue).Close() error`

Releases the database connection.  Safe to call multiple times (idempotent).

---

## Row type

```go
type Row struct {
    ID  int64
    Evt agent.AlertEvent
}
```

`ID` is the SQLite `ROWID` / `AUTOINCREMENT` primary key needed for `Ack`.

---

## Usage example

```go
import (
    "github.com/tripwire/agent/internal/agent"
    "github.com/tripwire/agent/internal/queue"
)

// Open the queue.
q, err := queue.Open("/var/lib/tripwire/alerts.db", logger)
if err != nil { ... }

// Register with the agent.
ag := agent.New(cfg, logger,
    agent.WithWatchers(fileWatcher, netWatcher),
    agent.WithQueue(q),
    agent.WithTransport(grpcTransport),
)
if err := ag.Start(ctx); err != nil { ... }
```

The agent orchestrator calls `q.Enqueue` for every `AlertEvent` it receives
from its watchers.  The transport layer is responsible for calling `Dequeue`
and `Ack` as part of its delivery loop.

---

## Driver

The queue uses [modernc.org/sqlite](https://pkg.go.dev/modernc.org/sqlite)
(`driver name: "sqlite"`), a pure-Go SQLite implementation with no CGO
dependency.  This means the agent binary can be built with `CGO_ENABLED=0`
for simpler cross-compilation and static linking.

---

## Testing

Unit tests live in `internal/queue/sqlite_queue_test.go` and cover:

| Test | Description |
|---|---|
| `TestEnqueue_DepthIncrements` | Depth increases with each enqueue |
| `TestEnqueue_PersistsAllFields` | All AlertEvent fields survive a round-trip |
| `TestDequeue_ReturnsInsertionOrder` | Rows are returned with ascending IDs |
| `TestDequeue_LimitRespected` | LIMIT clause caps the result set |
| `TestDequeue_EmptyQueueReturnsNil` | Empty queue returns nil slice without error |
| `TestAck_AcknowledgedEventsNotReDelivered` | Acked rows disappear from subsequent Dequeue |
| `TestAck_IdempotentForAlreadyAcknowledged` | Double-ack returns without error |
| `TestCrashRecovery_UnacknowledgedEventsReDeliveredAfterReopen` | Unacked rows survive close/reopen |
| `TestCrashRecovery_WALModeEnabledAfterReopen` | Database is readable after close/reopen |
| `TestClose_MultipleClosesAreIdempotent` | Close is safe to call multiple times |
| `TestClose_OperationsAfterCloseReturnError` | Enqueue/Dequeue/Ack on closed queue return error |
| `TestSatisfiesAgentQueueInterface` | Compile-time interface compliance check |

Run with:

```bash
go test ./internal/queue/...
```
