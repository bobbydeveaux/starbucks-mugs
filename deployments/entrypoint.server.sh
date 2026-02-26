#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# TripWire dashboard server — container entrypoint
#
# Responsibilities (in order):
#   1. Generate self-signed dev TLS certificates when none are mounted
#      (controlled by GENERATE_DEV_CERTS or absence of cert files).
#   2. Wait for PostgreSQL to accept connections (when RUN_MIGRATIONS=true).
#   3. Apply outstanding SQL migrations to the database (idempotent).
#   4. Exec the dashboard server binary with flags derived from environment.
#
# Environment variables:
#   DSN              PostgreSQL DSN  (e.g. postgres://user:pass@host/db)
#                    Required when RUN_MIGRATIONS=true.
#   POSTGRES_HOST    Hostname used by pg_isready (default: localhost)
#   POSTGRES_PORT    Port used by pg_isready (default: 5432)
#   GRPC_ADDR        gRPC listener address (default: :4443)
#   HTTP_ADDR        HTTP REST listener address (default: :8080)
#   TLS_CERT         Server TLS certificate path (default: /etc/tripwire/server.crt)
#   TLS_KEY          Server TLS private key path (default: /etc/tripwire/server.key)
#   TLS_CA           CA certificate path (default: /etc/tripwire/ca.crt)
#   JWT_PUBLIC_KEY   PEM RSA public key path for JWT validation (optional)
#   LOG_LEVEL        Log level: debug|info|warn|error (default: info)
#   RUN_MIGRATIONS   Set to "true" to run migrations before starting (default: false)
#   GENERATE_DEV_CERTS
#                    Set to "true" to always regenerate dev certs (default: false).
#                    Certs are also auto-generated when any of TLS_CERT, TLS_KEY,
#                    or TLS_CA are missing from the filesystem.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

log() {
    echo "[entrypoint] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

# ── Defaults ─────────────────────────────────────────────────────────────────
GRPC_ADDR="${GRPC_ADDR:-:4443}"
HTTP_ADDR="${HTTP_ADDR:-:8080}"
TLS_CERT="${TLS_CERT:-/etc/tripwire/server.crt}"
TLS_KEY="${TLS_KEY:-/etc/tripwire/server.key}"
TLS_CA="${TLS_CA:-/etc/tripwire/ca.crt}"
JWT_PUBLIC_KEY="${JWT_PUBLIC_KEY:-}"
LOG_LEVEL="${LOG_LEVEL:-info}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/app/migrations}"

# ── Dev TLS certificate generation ───────────────────────────────────────────
# Generate a self-signed CA + server certificate pair when any of the expected
# cert files are absent, or when GENERATE_DEV_CERTS=true.
#
# WARNING: Do NOT use these auto-generated certs in production.  Mount real
# operator-signed certificates via Docker volumes instead.
generate_dev_certs() {
    local cert_dir
    cert_dir="$(dirname "${TLS_CERT}")"
    mkdir -p "${cert_dir}"

    log "Generating self-signed development TLS certificates in ${cert_dir} ..."

    # CA key + self-signed CA certificate
    openssl genrsa -out "${cert_dir}/ca.key" 2048 2>/dev/null
    openssl req -new -x509 \
        -key "${cert_dir}/ca.key" \
        -out "${TLS_CA}" \
        -days 365 \
        -subj "/CN=TripWire-Dev-CA/O=TripWire" 2>/dev/null

    # Server key + CSR + sign with CA
    openssl genrsa -out "${TLS_KEY}" 2048 2>/dev/null
    openssl req -new \
        -key "${TLS_KEY}" \
        -out "${cert_dir}/server.csr" \
        -subj "/CN=dashboard/O=TripWire" 2>/dev/null
    openssl x509 -req \
        -in "${cert_dir}/server.csr" \
        -CA "${TLS_CA}" \
        -CAkey "${cert_dir}/ca.key" \
        -CAcreateserial \
        -out "${TLS_CERT}" \
        -days 365 \
        -extfile <(printf 'extendedKeyUsage=serverAuth,clientAuth\nsubjectAltName=DNS:localhost,DNS:server\n') \
        2>/dev/null

    # Clean up temporary files
    rm -f "${cert_dir}/server.csr" "${cert_dir}/ca.srl"

    log "Dev TLS certificates written: ${TLS_CA}  ${TLS_CERT}  ${TLS_KEY}"
    log "WARNING: These self-signed certificates are for LOCAL DEVELOPMENT ONLY."
}

# ── Wait for PostgreSQL ───────────────────────────────────────────────────────
wait_for_postgres() {
    local host="${POSTGRES_HOST:-localhost}"
    local port="${POSTGRES_PORT:-5432}"
    local max_attempts=30
    local attempt=1

    log "Waiting for PostgreSQL at ${host}:${port} ..."
    until pg_isready -h "${host}" -p "${port}" -q 2>/dev/null; do
        if [ "${attempt}" -ge "${max_attempts}" ]; then
            log "ERROR: PostgreSQL at ${host}:${port} did not become ready after ${max_attempts} attempts. Aborting."
            exit 1
        fi
        log "PostgreSQL not ready (attempt ${attempt}/${max_attempts}). Retrying in 2s..."
        attempt=$((attempt + 1))
        sleep 2
    done
    log "PostgreSQL is ready."
}

# ── Run SQL migrations ────────────────────────────────────────────────────────
# Applies *.up.sql migration files in lexicographic order, tracking applied
# versions in a schema_migrations table to ensure idempotency.
run_migrations() {
    local dsn="${DSN:?DSN environment variable is required when RUN_MIGRATIONS=true}"

    log "Running database migrations from ${MIGRATIONS_DIR} ..."

    # Create the migration tracking table if it does not yet exist.
    psql "${dsn}" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

    # Apply each *.up.sql file in sorted order, skipping already-applied versions.
    local migration_file version applied
    for migration_file in $(ls -1 "${MIGRATIONS_DIR}"/*.up.sql 2>/dev/null | sort); do
        version="$(basename "${migration_file}" .up.sql)"
        applied="$(psql "${dsn}" -tAq -c "SELECT COUNT(*) FROM schema_migrations WHERE version = '${version}'")"
        if [ "${applied}" = "0" ]; then
            log "Applying migration: ${version}"
            psql "${dsn}" < "${migration_file}"
            psql "${dsn}" -c "INSERT INTO schema_migrations (version) VALUES ('${version}')" > /dev/null
            log "Migration applied:  ${version}"
        else
            log "Skipping already-applied migration: ${version}"
        fi
    done

    log "All migrations applied."
}

# ── Step 1: TLS certificates ──────────────────────────────────────────────────
if [ "${GENERATE_DEV_CERTS:-false}" = "true" ] \
    || [ ! -f "${TLS_CERT}" ] \
    || [ ! -f "${TLS_KEY}" ] \
    || [ ! -f "${TLS_CA}" ]; then
    generate_dev_certs
fi

# ── Step 2 & 3: Migrations ────────────────────────────────────────────────────
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    wait_for_postgres
    run_migrations
fi

# ── Step 4: Start the server ──────────────────────────────────────────────────
ARGS=(
    "-grpc-addr" "${GRPC_ADDR}"
    "-http-addr"  "${HTTP_ADDR}"
    "-tls-cert"   "${TLS_CERT}"
    "-tls-key"    "${TLS_KEY}"
    "-tls-ca"     "${TLS_CA}"
    "-log-level"  "${LOG_LEVEL}"
)

if [ -n "${DSN:-}" ]; then
    ARGS+=("-dsn" "${DSN}")
fi

if [ -n "${JWT_PUBLIC_KEY:-}" ]; then
    ARGS+=("-jwt-pubkey" "${JWT_PUBLIC_KEY}")
fi

log "Starting TripWire dashboard server (grpc=${GRPC_ADDR} http=${HTTP_ADDR}) ..."
exec tripwire-server "${ARGS[@]}"
