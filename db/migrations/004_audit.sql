-- Migration: 004 - Create audit_entries table
-- golang-migrate up migration
-- Depends on: 001_hosts.sql

CREATE TABLE audit_entries (
    entry_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id      UUID        NOT NULL REFERENCES hosts(host_id),
    sequence_num BIGINT      NOT NULL,
    -- SHA-256 hex digest of this entry (64 hex characters).
    event_hash   CHAR(64)    NOT NULL,
    -- SHA-256 hex digest of the previous entry; all-zeros for the genesis entry.
    prev_hash    CHAR(64)    NOT NULL,
    -- Full event payload stored as JSONB for flexible querying.
    payload      JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Enforce monotonic sequence per host.
    UNIQUE (host_id, sequence_num)
);

-- Index covering time-range audit queries per host (entity_id = host_id in this schema).
CREATE INDEX idx_audit_entries_entity_id ON audit_entries (host_id, created_at);
