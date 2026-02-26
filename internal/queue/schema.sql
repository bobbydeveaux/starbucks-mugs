-- alert_queue: durable local buffer for TripWire alert events.
--
-- WAL journal mode and NORMAL synchronous durability are applied by the Go
-- code at connection time via PRAGMA statements; they cannot be set from DDL.
--
-- Schema design notes:
--   • id         – monotonically increasing rowid used for delivery ordering.
--   • delivered  – 0 = pending (default), 1 = acknowledged and safe to ignore.
--   • detail     – JSON-encoded map[string]any from AlertEvent.Detail.
--   • ts         – RFC3339Nano UTC timestamp of the original sensor event.
--   • enqueued_at – wall-clock time the row was written (set by SQLite default).

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

-- Covering index that makes the common dequeue query
-- (WHERE delivered = 0 ORDER BY id LIMIT n) an index-only scan.
CREATE INDEX IF NOT EXISTS idx_alert_queue_pending
    ON alert_queue (delivered, id);
