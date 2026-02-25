-- Migration 002: Create alerts table with monthly range partitioning
-- Stores all tripwire alert events received from agents.
-- Partitioned by received_at (dashboard ingestion time) for efficient
-- time-range queries and 90-day rolling retention via partition drops.

CREATE TYPE tripwire_type  AS ENUM ('FILE', 'NETWORK', 'PROCESS');
CREATE TYPE severity_level AS ENUM ('INFO', 'WARN', 'CRITICAL');

-- Parent partitioned table. The partition key (received_at) must be part
-- of the PRIMARY KEY to satisfy PostgreSQL's partitioning constraint.
CREATE TABLE alerts (
    alert_id      UUID           NOT NULL DEFAULT gen_random_uuid(),
    host_id       UUID           NOT NULL,
    timestamp     TIMESTAMPTZ    NOT NULL,
    tripwire_type tripwire_type  NOT NULL,
    rule_name     TEXT           NOT NULL,
    event_detail  JSONB          NOT NULL DEFAULT '{}',
    severity      severity_level NOT NULL,
    received_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    PRIMARY KEY (alert_id, received_at),

    CONSTRAINT fk_alerts_host
        FOREIGN KEY (host_id) REFERENCES hosts (host_id)
) PARTITION BY RANGE (received_at);

-- ── Example monthly child partitions ─────────────────────────────────────────
-- New partitions should be created by an automated maintenance job (e.g.
-- pg_cron) before the month boundary. Old partitions are dropped (not
-- truncated) to satisfy the 90-day retention policy without full-table locks.

CREATE TABLE alerts_2026_02 PARTITION OF alerts
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

CREATE TABLE alerts_2026_03 PARTITION OF alerts
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE alerts_2026_04 PARTITION OF alerts
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- ── Indexes ───────────────────────────────────────────────────────────────────
-- Indexes declared on the parent are automatically propagated to all partitions.

-- Primary query pattern: filter by host across all time ranges.
CREATE INDEX idx_alerts_host_id
    ON alerts (host_id);

-- Primary query pattern: filter by severity with time-range pruning.
CREATE INDEX idx_alerts_severity_received_at
    ON alerts (severity, received_at);

-- Agent-clock timestamp lookup (distinct from partition key received_at).
CREATE INDEX idx_alerts_timestamp
    ON alerts (timestamp);
