# TripWire Agent — Local Alert Queue

This document describes the WAL-mode SQLite-backed alert queue used by the
TripWire agent to buffer security events for at-least-once delivery to the
central dashboard.

---

## Overview

When an alert event fires on the monitored host, the agent orchestrator
(`internal/agent`) records it in two places:

1. **Local queue** (`internal/queue.SQLiteQueue`) — a WAL-mode SQLite
   database on the agent's local filesystem that survives process crashes.
2. **Transport** — a gRPC stream that forwards the event to the dashboard.

If the network is unavailable or the transport fails, the event is already
persisted in the queue. A delivery goroutine can call `Dequeue` later, and
after the transport confirms receipt it calls `Ack` to mark the event as
delivered. Restarting the agent re-delivers any events that were enqueued but
not yet acknowledged.

---

## Package: `internal/queue`

**Files:**

| File | Description |
|------|-------------|
| `schema.sql` | Canonical DDL for the `alert_queue` table and its index |
| `sqlite_queue.go` | `SQLiteQueue` implementation |
| `sqlite_queue_test.go` | Unit and crash-recovery tests |

---

## SQLite Schema

```sql
CREATE TABLE alert_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tripwire_type TEXT    NOT NULL,
    rule_name     TEXT    NOT NULL,
    severity      TEXT    NOT NULL,
    ts            TEXT    NOT NULL,   -- RFC3339Nano UTC event timestamp
    detail        TEXT    NOT NULL DEFAULT '{}',
    enqueued_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered     INTEGER NOT NULL DEFAULT 0  -- 0 = pending, 1 = acknowledged
);

CREATE INDEX idx_alert_queue_pending ON alert_queue (delivered, id);
```

The index covers the common dequeue query (`WHERE delivered = 0 ORDER BY id
LIMIT n`) as an index-only scan.

---

## WAL Mode

The database is opened with:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

WAL (Write-Ahead Log) mode allows concurrent readers while a single writer is
active, which is important for the agent's multi-goroutine architecture.
`synchronous = NORMAL` ensures that committed transactions survive an
application crash (but not necessarily an OS crash or power loss), while
giving a significant write-throughput improvement over the default `FULL` mode.

---

## API

### `New(path string) (*SQLiteQueue, error)`

Opens or creates the SQLite database at `path`. Pass `":memory:"` for an
in-memory database (tests only — data is lost on close).

`New` enables WAL mode, applies the schema, and seeds the internal `Depth`
counter from the count of undelivered rows, so `Depth()` is accurate
immediately after a crash-recovery restart.

### `Enqueue(ctx, evt AlertEvent) error`

Persists the event with `delivered = 0`. Implements `agent.Queue`.

### `Dequeue(ctx, n int) ([]PendingEvent, error)`

Returns up to `n` unacknowledged events in insertion order (oldest first).
Does **not** mark events as delivered; call `Ack` to do that.

```go
type PendingEvent struct {
    ID  int64
    Evt agent.AlertEvent
}
```

### `Ack(ctx, ids []int64) error`

Marks the events with the given IDs as `delivered = 1`. Idempotent — calling
it multiple times with the same IDs is safe. The `Depth` counter is decremented
by the number of rows that transition from pending to delivered.

### `Depth() int`

Returns the number of pending (undelivered) events. Reads from an atomic
counter; never blocks. Implements `agent.Queue`.

### `Close() error`

Closes the database connection. Implements `agent.Queue`.

---

## At-Least-Once Delivery Semantics

```
Agent goroutine                    Delivery goroutine
──────────────────                 ──────────────────
evt := <-watcher.Events()
queue.Enqueue(ctx, evt)  ─────────► stored with delivered=0
transport.Send(ctx, evt)
                                   pending := queue.Dequeue(ctx, 10)
                                   for _, pe := range pending {
                                       transport.Send(ctx, pe.Evt)
                                       queue.Ack(ctx, []int64{pe.ID})
                                   }
```

If the process crashes between `Enqueue` and `Ack`, the event is returned
again by the next `Dequeue` after restart, guaranteeing delivery even during
temporary transport outages.

---

## Usage Example

```go
import (
    "github.com/tripwire/agent/internal/queue"
    "github.com/tripwire/agent/internal/agent"
)

// Open the queue (WAL mode enabled automatically).
q, err := queue.New("/var/lib/tripwire/agent.db")
if err != nil {
    log.Fatal(err)
}
defer q.Close()

// Wire into the agent orchestrator.
ag := agent.New(cfg, logger, agent.WithQueue(q))
if err := ag.Start(ctx); err != nil {
    log.Fatal(err)
}

// Deliver pending events in a background goroutine.
go func() {
    for {
        pending, _ := q.Dequeue(ctx, 50)
        var acked []int64
        for _, pe := range pending {
            if err := transport.Send(ctx, pe.Evt); err == nil {
                acked = append(acked, pe.ID)
            }
        }
        q.Ack(ctx, acked)
        time.Sleep(500 * time.Millisecond)
    }
}()
```

---

## Testing

The test suite in `sqlite_queue_test.go` covers:

| Test | Scenario |
|------|----------|
| `TestNew_InMemory_EmptyDepth` | Fresh in-memory queue starts with depth 0 |
| `TestNew_FileDB_CreatesFile` | Opens a real file on disk without error |
| `TestEnqueue_IncreasesDepth` | Depth counter increments on enqueue |
| `TestEnqueue_MultipleEvents_DepthAccumulates` | Multiple enqueues accumulate depth |
| `TestDequeue_ReturnsEventsInInsertionOrder` | Dequeue preserves FIFO order |
| `TestDequeue_RespectsLimit` | Dequeue returns at most `n` events |
| `TestDequeue_ZeroLimit_ReturnsNil` | Dequeue(0) is a no-op |
| `TestDequeue_PreservesTimestamp` | Event timestamp round-trips faithfully |
| `TestAck_MarksEventDelivered` | Acked events are not re-delivered |
| `TestAck_Idempotent` | Double-acking the same ID is safe |
| `TestAck_EmptyIDs_IsNoop` | Ack(nil) / Ack([]) return nil |
| `TestAck_PartialAck_LeavesPendingEvents` | Unacked events remain in queue |
| `TestCrashRecovery_UnacknowledgedEventsRedelivered` | Unacked events survive restart |
| `TestCrashRecovery_AllAcked_EmptyOnRestart` | Fully-acked queue is empty after restart |
| `TestSQLiteQueue_ImplementsQueueInterface` | Compile-time interface check |

Run the tests with:

```bash
go test ./internal/queue/...
```

---

## Dependency

The queue uses [`modernc.org/sqlite`](https://pkg.go.dev/modernc.org/sqlite)
— a pure-Go port of SQLite that requires no CGO and no system SQLite library.
This makes the agent binary easy to cross-compile and deploy.
