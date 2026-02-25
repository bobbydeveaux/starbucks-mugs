-- Migration 001: Create hosts table
-- Tracks all registered TripWire agents and their monitored hosts.

CREATE TYPE host_status AS ENUM ('ONLINE', 'OFFLINE', 'DEGRADED');

CREATE TABLE hosts (
    host_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname      TEXT        NOT NULL,
    ip_address    INET,
    platform      TEXT,
    agent_version TEXT,
    last_seen     TIMESTAMPTZ,
    status        host_status NOT NULL DEFAULT 'OFFLINE',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT hosts_hostname_unique UNIQUE (hostname)
);

CREATE INDEX idx_hosts_status ON hosts (status);
