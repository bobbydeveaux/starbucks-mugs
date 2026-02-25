#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------
# FileGuard container entrypoint
#
# Environment variables:
#   RUN_MIGRATIONS  - set to "true" to run alembic upgrade head
#                     before starting the application (default: false)
#   DATABASE_URL    - required; used by alembic and the application
# ----------------------------------------------------------------

log() {
    echo "[entrypoint] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

# Wait for PostgreSQL to be ready before attempting migrations.
# Uses a simple retry loop since netcat may not be available in all images.
wait_for_postgres() {
    local max_attempts=30
    local attempt=1

    log "Waiting for PostgreSQL to be ready..."
    until python - <<'PYEOF' 2>/dev/null
import asyncio, os, sys
import asyncpg

async def check():
    url = os.environ.get("DATABASE_URL", "")
    # asyncpg DSN uses postgresql:// not postgresql+asyncpg://
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(url, timeout=2)
        await conn.close()
        sys.exit(0)
    except Exception:
        sys.exit(1)

asyncio.run(check())
PYEOF
    do
        if [ "$attempt" -ge "$max_attempts" ]; then
            log "ERROR: PostgreSQL did not become ready after ${max_attempts} attempts. Aborting."
            exit 1
        fi
        log "PostgreSQL not ready yet (attempt ${attempt}/${max_attempts}). Retrying in 2s..."
        attempt=$((attempt + 1))
        sleep 2
    done
    log "PostgreSQL is ready."
}

# Run database migrations via Alembic
run_migrations() {
    log "Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    log "Migrations complete."
}

# ---- Main entrypoint logic ----

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    wait_for_postgres
    run_migrations
fi

log "Starting application: $*"
exec "$@"
