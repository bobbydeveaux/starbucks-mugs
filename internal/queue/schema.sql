-- schema.sql initialises the WAL-mode SQLite database used by the TripWire
-- agent's local alert queue.  The database stores alert events emitted by
-- watcher components and buffers them until they are acknowledged by the
-- transport layer (at-least-once delivery semantics).
--
-- Journal mode and synchronous settings are applied first so that all
-- subsequent operations run under WAL mode.  WAL (Write-Ahead Logging) allows
-- concurrent reads and a single writer without blocking, and provides much
-- better throughput than the default DELETE journal mode for the agent's
-- workload pattern (frequent small inserts, occasional reads and updates).

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- alerts holds every queued event.  Rows are never deleted; instead the
-- delivered column is set to 1 when the transport layer has acknowledged the
-- event.  This preserves a complete local history and supports idempotent
-- re-delivery after a crash.
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,

    -- AlertEvent fields.
    tripwire_type TEXT    NOT NULL,          -- "FILE", "NETWORK", or "PROCESS"
    rule_name     TEXT    NOT NULL,
    severity      TEXT    NOT NULL,          -- "INFO", "WARN", or "CRITICAL"
    ts            TEXT    NOT NULL,          -- RFC3339Nano timestamp (UTC)
    detail        TEXT    NOT NULL DEFAULT '{}', -- JSON object of type-specific metadata

    -- Delivery tracking.
    delivered     INTEGER NOT NULL DEFAULT 0,   -- 0 = pending, 1 = acknowledged

    -- Audit timestamp (set by SQLite at insert time).
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- idx_alerts_pending accelerates the most common query pattern: fetching
-- undelivered rows in insertion order (Dequeue) and counting pending rows
-- (Depth).
CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts (delivered, id);
