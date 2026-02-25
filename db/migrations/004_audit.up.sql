-- Migration 004: Create audit_entries table
-- Stores tamper-evident forensic records using SHA-256 hash chaining.
-- Each entry contains the hash of the previous entry so that any
-- modification to the chain is detectable during verification.
-- Depends on: hosts (001).

CREATE TABLE audit_entries (
    entry_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id      UUID        NOT NULL,
    -- entity_id references the audited subject (alert_id, rule_id, host_id,
    -- etc.) without a hard FK so heterogeneous entity types can be tracked.
    entity_id    UUID,
    sequence_num BIGINT      NOT NULL,
    -- SHA-256 hex digest of this entry's canonical payload (64 hex chars).
    event_hash   CHAR(64)    NOT NULL,
    -- SHA-256 hex digest of the previous entry; genesis entry uses all-zeros.
    prev_hash    CHAR(64)    NOT NULL
        DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
    -- Full event payload including tripwire type, rule, and event metadata.
    payload      JSONB       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_audit_host
        FOREIGN KEY (host_id) REFERENCES hosts (host_id),
    -- Enforce monotonically increasing sequence per host for chain integrity.
    CONSTRAINT audit_host_sequence_unique
        UNIQUE (host_id, sequence_num)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Primary forensic query: retrieve all audit events for a given entity
-- within a time window (e.g. all events touching a specific alert or host).
CREATE INDEX idx_audit_entity_id_created_at
    ON audit_entries (entity_id, created_at);

-- Host-scoped chain walk: retrieve all entries for a host ordered by sequence.
CREATE INDEX idx_audit_host_id_sequence
    ON audit_entries (host_id, sequence_num);

-- Time-range queries across all hosts for dashboard audit log view.
CREATE INDEX idx_audit_created_at
    ON audit_entries (created_at);
