-- Migration: 001 - Create hosts table
-- golang-migrate up migration

CREATE TYPE host_status AS ENUM ('ONLINE', 'OFFLINE', 'DEGRADED');

CREATE TABLE hosts (
    host_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname      TEXT        UNIQUE NOT NULL,
    ip_address    INET,
    platform      TEXT,
    agent_version TEXT,
    last_seen     TIMESTAMPTZ,
    status        host_status NOT NULL DEFAULT 'OFFLINE'
);
