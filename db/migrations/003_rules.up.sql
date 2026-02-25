-- Migration 003: Create tripwire_rules table
-- Stores the configured tripwire rules that define what to monitor on each host.
-- A NULL host_id means the rule is global (applied to all hosts).
-- Depends on: hosts (001), tripwire_type and severity_level enums (002).

CREATE TABLE tripwire_rules (
    rule_id    UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id    UUID,
    rule_type  tripwire_type  NOT NULL,
    target     TEXT           NOT NULL,
    severity   severity_level NOT NULL DEFAULT 'WARN',
    enabled    BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_rules_host
        FOREIGN KEY (host_id) REFERENCES hosts (host_id)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Lookup rules assigned to a specific host (includes NULLs via separate query).
CREATE INDEX idx_rules_host_id
    ON tripwire_rules (host_id);

-- Filter active rules by type (common at agent config-sync time).
CREATE INDEX idx_rules_type_enabled
    ON tripwire_rules (rule_type, enabled);
