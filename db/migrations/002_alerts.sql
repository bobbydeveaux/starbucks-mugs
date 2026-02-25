-- Migration: 002 - Create alerts table with monthly partitioning
-- golang-migrate up migration

CREATE TYPE tripwire_type AS ENUM ('FILE', 'NETWORK', 'PROCESS');

CREATE TYPE severity_level AS ENUM ('INFO', 'WARN', 'CRITICAL');

-- Declarative monthly partitioning on received_at.
-- The PRIMARY KEY must include the partition key column.
CREATE TABLE alerts (
    alert_id      UUID           NOT NULL DEFAULT gen_random_uuid(),
    host_id       UUID           NOT NULL REFERENCES hosts(host_id),
    timestamp     TIMESTAMPTZ    NOT NULL,
    tripwire_type tripwire_type  NOT NULL,
    rule_name     TEXT           NOT NULL,
    event_detail  JSONB,
    severity      severity_level NOT NULL,
    received_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (alert_id, received_at)
) PARTITION BY RANGE (received_at);

-- Example child partition covering February 2026.
-- Operators should create future partitions ahead of time (e.g. via pg_cron).
CREATE TABLE alerts_y2026m02 PARTITION OF alerts
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- Index covering host-scoped alert lookups.
CREATE INDEX idx_alerts_host_id ON alerts (host_id);

-- Index covering severity + time-range queries (supports partition pruning).
CREATE INDEX idx_alerts_severity_received_at ON alerts (severity, received_at);
