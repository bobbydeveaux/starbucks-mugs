# PostgreSQL Storage Layer

This document describes the database schema and Go storage implementation for
the TripWire dashboard server.

## Overview

The dashboard persists four entity types to PostgreSQL 15+:

| Table | Description |
|---|---|
| `hosts` | Registered monitoring agents and their liveness state |
| `alerts` | Security alerts emitted by tripwire sensors (monthly-partitioned) |
| `tripwire_rules` | Operator-defined monitoring rules |
| `audit_entries` | Tamper-evident audit log with SHA-256 hash chaining |

## Database Migrations

Migration files live in `db/migrations/` and are applied with
[golang-migrate](https://github.com/golang-migrate/migrate).  Run them against
a fresh database with:

```sh
migrate -path db/migrations -database "postgres://..." up
```

| File | Creates |
|---|---|
| `001_hosts.sql` | `hosts` table + `host_status` ENUM |
| `002_alerts.sql` | `alerts` partitioned table + `tripwire_type` + `severity_level` ENUMs |
| `003_rules.sql` | `tripwire_rules` table |
| `004_audit.sql` | `audit_entries` table |

### Alert Partitioning

`alerts` is declared with `PARTITION BY RANGE (received_at)`.  A single example
child partition `alerts_y2026m02` (covering February 2026) is created by
migration 002.  Operators must create future partitions ahead of time, for
example via a monthly `pg_cron` job:

```sql
CREATE TABLE alerts_y2026m03 PARTITION OF alerts
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
```

Time-range queries that bound `received_at` benefit from PostgreSQL's partition
pruning, meaning only the relevant monthly partition is scanned rather than the
full table.

## Go Package: `internal/server/storage`

### `models.go`

Defines the Go structs that map directly to the four database tables:

- `Host` — maps to `hosts`
- `Alert` — maps to `alerts`; the `EventDetail` field uses `json.RawMessage`
  for lossless JSONB round-trips
- `TripwireRule` — maps to `tripwire_rules`
- `AuditEntry` — maps to `audit_entries`

Each struct uses plain Go types (`string`, `time.Time`, `*time.Time`,
`json.RawMessage`) to avoid tight coupling to the pgx/pgtype API.

### `postgres.go`

`Store` wraps a `*pgxpool.Pool` and provides:

#### Batch Alert Insertion

```go
s, _ := storage.New(ctx, connStr, 100, 100*time.Millisecond)
defer s.Close(ctx)

alert := storage.Alert{...}
s.BatchInsertAlerts(ctx, alert)  // buffered; flush is automatic
```

`BatchInsertAlerts` appends to an in-memory buffer protected by a `sync.Mutex`.
The buffer is flushed via `pgx.SendBatch` in two situations:

1. **Size threshold** — when the buffer reaches `batchSize` rows the caller's
   goroutine flushes synchronously before returning.
2. **Timer** — a background goroutine fires every `flushInterval` (default
   100 ms) and flushes whatever is buffered, even if batchSize has not been
   reached.

`Flush` can also be called directly for deterministic flushing in tests or on
graceful shutdown.

#### Alert Queries

```go
sev := storage.SeverityCritical
alerts, err := s.QueryAlerts(ctx, storage.AlertQuery{
    HostID:   "...",
    Severity: &sev,
    From:     time.Now().Add(-24 * time.Hour),
    To:       time.Now(),
    Limit:    100,
    Offset:   0,
})
```

`QueryAlerts` always requires `From` and `To` so that PostgreSQL can apply
partition pruning.  Optional filters: `HostID`, `Severity`.

#### CRUD Helpers

| Method | Description |
|---|---|
| `UpsertHost` | Insert or update on hostname conflict |
| `GetHost` | Fetch by UUID |
| `ListHosts` | All hosts, ordered by hostname |
| `CreateRule` | Insert a tripwire rule |
| `GetRule` | Fetch by UUID |
| `ListRules(hostID)` | Rules for a host + global rules (NULL host_id) |
| `UpdateRule` | Replace all mutable rule fields |
| `DeleteRule` | Remove by UUID |
| `InsertAuditEntry` | Persist one tamper-evident audit record |
| `QueryAuditEntries` | Fetch entries for a host within a time range |

## Integration Tests

Tests live in `internal/server/storage/postgres_test.go` behind the
`integration` build tag.  They require a Docker-capable environment to start a
`postgres:15-alpine` container via
[testcontainers-go](https://golang.testcontainers.org/).

```sh
go test -tags integration -v ./internal/server/storage/...
```

The tests cover:

- Host upsert, update, and list
- Alert batch insert flushed on size threshold
- Alert batch insert flushed on timer interval
- Alert query with severity filter
- `event_detail` (JSONB) round-trip without data loss
- TripwireRule CRUD (create / get / update / delete)
- Global vs host-scoped rule listing
- AuditEntry insert, query, sequence ordering, and hash-chain integrity
