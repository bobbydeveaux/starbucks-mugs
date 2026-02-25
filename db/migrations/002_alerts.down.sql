-- Rollback 002: Drop alerts table and related types
-- Dropping the parent table cascades to all child partitions automatically.

DROP TABLE IF EXISTS alerts;

DROP TYPE IF EXISTS severity_level;
DROP TYPE IF EXISTS tripwire_type;
