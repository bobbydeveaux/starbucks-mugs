-- Migration: 003 - Create tripwire_rules table
-- golang-migrate up migration
-- Depends on: 001_hosts.sql (host_status type), 002_alerts.sql (tripwire_type, severity_level types)

CREATE TABLE tripwire_rules (
    rule_id   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL host_id means the rule applies globally to all hosts.
    host_id   UUID           REFERENCES hosts(host_id),
    rule_type tripwire_type  NOT NULL,
    target    TEXT           NOT NULL,
    severity  severity_level NOT NULL,
    enabled   BOOLEAN        NOT NULL DEFAULT TRUE
);
