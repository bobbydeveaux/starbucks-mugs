# ============================================================
# Stage 1: Builder — install Python dependencies
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages into a prefix so they can be copied cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: Runtime — minimal production image
# ============================================================
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="FileGuard API" \
      org.opencontainers.image.description="Security-focused file processing gateway" \
      org.opencontainers.image.vendor="RiverSafe" \
      org.opencontainers.image.version="1.0.0"

# Install runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a dedicated non-root user
RUN groupadd --gid 1001 fileguard \
    && useradd --uid 1001 --gid fileguard --shell /bin/bash --create-home fileguard

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source code
COPY fileguard/ ./fileguard/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini

# Copy and configure the entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set ownership so the non-root user can read all files
RUN chown -R fileguard:fileguard /app /entrypoint.sh

# Switch to non-root user
USER fileguard

# Expose the FastAPI port
EXPOSE 8000

# Health check — hits the /healthz endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "fileguard.main:app", "--host", "0.0.0.0", "--port", "8000"]
