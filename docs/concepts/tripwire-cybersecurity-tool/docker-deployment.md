# TripWire Dashboard — Docker Deployment

This document covers the Docker container setup for the TripWire dashboard
server, including the Dockerfile, entrypoint script, and Docker Compose
configuration for local development and staging deployments.

---

## Files

| File | Description |
|------|-------------|
| `deployments/Dockerfile.server` | Multi-stage Dockerfile for the dashboard server binary |
| `deployments/entrypoint.server.sh` | Container entrypoint: cert generation, migrations, server startup |
| `deployments/docker-compose.yml` | Compose file: server + PostgreSQL for local development |

---

## Quick Start (Local Development)

```sh
# Build and start the full stack
docker compose -f deployments/docker-compose.yml up --build

# Verify the server is healthy
curl http://localhost:8080/healthz
# Expected: {"status":"ok"}

# Stop containers (data volume is preserved)
docker compose -f deployments/docker-compose.yml down

# Stop containers AND remove data
docker compose -f deployments/docker-compose.yml down -v
```

### What happens on first `docker compose up`

1. **Build** — Docker builds `tripwire-server:local` from `deployments/Dockerfile.server`.
2. **PostgreSQL** starts and passes its health check.
3. **Server entrypoint** runs:
   - Generates self-signed development TLS certificates in `/etc/tripwire/`.
   - Waits for PostgreSQL to accept connections via `pg_isready`.
   - Applies all `db/migrations/*.up.sql` files in order, tracking applied
     versions in a `schema_migrations` table for idempotency.
   - Starts the `tripwire-server` binary.
4. **Health check** — Compose polls `GET /healthz` until HTTP 200 is returned.

---

## Dockerfile Overview (`deployments/Dockerfile.server`)

The Dockerfile uses a two-stage build:

### Stage 1 — Builder (`golang:1.22-bookworm`)

```dockerfile
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux \
    go build -ldflags="-s -w" -o /tripwire-server ./cmd/server
```

- `CGO_ENABLED=0` produces a fully static binary with no glibc dependency.
- `-ldflags="-s -w"` strips the symbol table and DWARF debug info, reducing
  binary size.

### Stage 2 — Runtime (`debian:bookworm-slim`)

Installs four packages and nothing else:

| Package | Purpose |
|---------|---------|
| `ca-certificates` | System CA bundle for outbound TLS |
| `curl` | Liveness probe (`HEALTHCHECK`) |
| `openssl` | Dev TLS certificate generation in the entrypoint |
| `postgresql-client` | `psql` + `pg_isready` for the migration runner |

The `tripwire` system user (UID/GID 1001) owns `/etc/tripwire/` and runs the
server process — the container never runs as root after image build.

**Exposed ports:**

| Port | Protocol | Description |
|------|----------|-------------|
| `4443` | TCP | gRPC mTLS (TripWire agents) |
| `8080` | TCP | HTTP REST API + `/healthz` |

---

## Entrypoint Script (`deployments/entrypoint.server.sh`)

The entrypoint is the single executable layer between container start and the
server process.  It performs three tasks before calling `exec tripwire-server`.

### 1. TLS Certificate Generation (dev only)

When any of `TLS_CERT`, `TLS_KEY`, or `TLS_CA` are absent from the filesystem
(or when `GENERATE_DEV_CERTS=true`), the entrypoint generates:

- A self-signed 2048-bit RSA CA certificate (`ca.crt`)
- A server certificate signed by that CA (`server.crt` + `server.key`)

**These certificates are for local development only.** See [Using Real
Certificates](#using-real-tls-certificates-in-production) for production setup.

### 2. PostgreSQL Readiness Wait

When `RUN_MIGRATIONS=true`, the entrypoint calls `pg_isready` in a retry loop
(up to 30 attempts, 2-second intervals) before touching the database.

### 3. SQL Migration Runner

Applies all `db/migrations/*.up.sql` files in lexicographic order using `psql`.
Applied versions are tracked in a `schema_migrations` table:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Re-running `docker compose up` is safe: already-applied migrations are skipped.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DSN` | — | PostgreSQL DSN (`postgres://user:pass@host/db`). Required when `RUN_MIGRATIONS=true`. |
| `POSTGRES_HOST` | `localhost` | Host for `pg_isready` readiness check |
| `POSTGRES_PORT` | `5432` | Port for `pg_isready` readiness check |
| `GRPC_ADDR` | `:4443` | gRPC listener address |
| `HTTP_ADDR` | `:8080` | HTTP REST listener address |
| `TLS_CERT` | `/etc/tripwire/server.crt` | Server TLS certificate path |
| `TLS_KEY` | `/etc/tripwire/server.key` | Server TLS private key path |
| `TLS_CA` | `/etc/tripwire/ca.crt` | CA certificate path |
| `JWT_PUBLIC_KEY` | — | PEM RSA public key for JWT validation (optional) |
| `LOG_LEVEL` | `info` | Log verbosity: `debug` \| `info` \| `warn` \| `error` |
| `RUN_MIGRATIONS` | `false` | Set `"true"` to apply migrations before starting |
| `GENERATE_DEV_CERTS` | `false` | Set `"true"` to force-regenerate dev certs |
| `MIGRATIONS_DIR` | `/app/migrations` | Directory containing `*.up.sql` files |

---

## Docker Compose Services (`deployments/docker-compose.yml`)

### `server`

Builds from `deployments/Dockerfile.server` with context `..` (repo root).

Key configuration:

```yaml
environment:
  DSN: "postgres://tripwire:tripwire@postgres:5432/tripwire?sslmode=disable"
  POSTGRES_HOST: postgres
  RUN_MIGRATIONS: "true"
  GENERATE_DEV_CERTS: "true"
depends_on:
  postgres:
    condition: service_healthy
```

The `depends_on` condition ensures PostgreSQL passes its own health check before
the server container starts — preventing migration failures due to a cold-starting
database.

### `postgres`

```yaml
image: postgres:16-alpine
volumes:
  - postgres_data:/var/lib/postgresql/data
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U tripwire -d tripwire"]
```

The `postgres_data` named volume persists the data directory across container
restarts.  Running `docker compose down` (without `-v`) preserves the volume.

---

## Using Real TLS Certificates in Production

For staging or production, replace the auto-generated dev certs with
operator-managed certificates:

1. Generate the CA and a dashboard server certificate:
   ```sh
   sudo deployments/certs/generate_ca.sh
   sudo deployments/certs/generate_agent_cert.sh dashboard.internal
   ```

2. Mount the cert directory as a read-only volume in the Compose file:
   ```yaml
   server:
     volumes:
       - /etc/tripwire/dashboard:/etc/tripwire:ro
     environment:
       GENERATE_DEV_CERTS: "false"
   ```

3. Refer to [PKI Setup](./deployments/certs/README.md) for the full operator
   workflow including CA key storage and certificate renewal procedures.

---

## Volume Persistence

```
docker compose down         # stops containers; postgres_data volume is kept
docker compose up           # restarts with existing data; migrations are skipped
docker compose down -v      # stops containers AND removes postgres_data
```

Data survives:
- Container restarts (`restart: unless-stopped`)
- `docker compose down` / `docker compose up` cycles
- Image rebuilds (`docker compose up --build`)

Data is lost only on explicit `docker compose down -v` or manual `docker volume rm`.

---

## Port Reference

| Host port | Container port | Description |
|-----------|----------------|-------------|
| `8080` | `8080` | HTTP REST API + `/healthz` |
| `4443` | `4443` | gRPC mTLS (agent connections) |
| `5432` | `5432` | PostgreSQL (direct access for dev tooling) |

---

## Troubleshooting

### Server container exits immediately

Check logs:
```sh
docker compose -f deployments/docker-compose.yml logs server
```

Common causes:
- **TLS cert generation failed**: `openssl` output in logs will indicate the
  problem.
- **Migration failed**: `psql` will print the SQL error.  Ensure the DSN is
  correct and PostgreSQL is healthy.

### Health check fails beyond `start_period`

The `/healthz` endpoint returns HTTP 200 as soon as the server is listening.
If the check fails after 30 seconds:
- Verify port 8080 is not blocked by another process.
- Check that `HTTP_ADDR` matches the health check port.
- Inspect logs for server startup errors (cert loading, DSN errors).

### `pg_isready` times out

The entrypoint retries 30 times with 2-second intervals.  If PostgreSQL is
still not ready after 60 seconds:
- Check the `postgres` container logs: `docker compose logs postgres`.
- Verify that `POSTGRES_HOST` and `POSTGRES_PORT` match the service name and
  port defined in the Compose file.

### Stale migrations on re-run

If a migration file is changed after it has been applied, the `schema_migrations`
table will have the version recorded and the new content will NOT be applied
automatically.  To re-run a migration:

```sql
DELETE FROM schema_migrations WHERE version = '002_alerts';
```

Then restart with `RUN_MIGRATIONS=true`.  Be cautious: if the migration is not
idempotent, it may fail or produce duplicate data.
