# FileGuard

FileGuard is a security-focused file processing gateway that inspects, sanitises, and redacts uploaded files before they are accepted into critical systems.

## Documentation Index

| Document | Description |
|---|---|
| [PRD.md](PRD.md) | Product Requirements Document |
| [HLD.md](HLD.md) | High-Level Design (architecture overview) |
| [LLD.md](LLD.md) | Low-Level Design (implementation details) |

## Quick Start (Local Development)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 24+
- [Docker Compose](https://docs.docker.com/compose/) v2.20+

### Start all services

```bash
docker compose up --build
```

This starts:
- **fileguard-api** on `http://localhost:8000`
- **PostgreSQL 16** on `localhost:5432`
- **Redis 7** on `localhost:6379`
- **ClamAV** (clamd) on `localhost:3310`

Migrations run automatically on API startup (`RUN_MIGRATIONS=true`).

### Verify the API is running

```bash
curl http://localhost:8000/healthz
# {"status": "ok"}
```

### Run migrations manually

```bash
docker compose run --rm app alembic upgrade head
```

### Stop services

```bash
docker compose down
```

To also remove volumes (database data, ClamAV signatures):

```bash
docker compose down -v
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Yes | — | Redis DSN (`redis://...`) |
| `SECRET_KEY` | Yes | — | HMAC signing key for audit log entries |
| `CLAMAV_HOST` | No | `clamav` | ClamAV daemon hostname |
| `CLAMAV_PORT` | No | `3310` | ClamAV daemon TCP port |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `ENVIRONMENT` | No | `development` | Deployment environment label |
| `MAX_FILE_SIZE_MB` | No | `50` | Maximum synchronous scan file size |
| `THREAD_POOL_WORKERS` | No | `4` | Worker threads for CPU-bound extraction |
| `REPORTS_DIR` | No | `/tmp/fileguard/reports` | Local directory where generated compliance report files are stored |
| `REPORT_CADENCE` | No | `daily` | Beat schedule cadence for automatic report generation (`daily` or `weekly`) |
| `RUN_MIGRATIONS` | No | `false` | Run `alembic upgrade head` on container start |

## API Reference

OpenAPI spec: `http://localhost:8000/v1/openapi.json`
Swagger UI: `http://localhost:8000/v1/docs`

## Authentication

All API endpoints (except `/healthz`, `/v1/docs`, and `/v1/openapi.json`) require a
`Bearer` token in the `Authorization` header.  Two authentication paths are supported:

### API Key

Pass a raw API key as the bearer token.  The key is compared to the bcrypt hash
stored in `tenant_config.api_key_hash` using `bcrypt.checkpw`.

```bash
curl -H "Authorization: Bearer <api-key>" http://localhost:8000/v1/scan
```

### OAuth 2.0 JWT

Pass a compact JWT as the bearer token.  The middleware:
1. Reads the `aud` claim to identify the tenant (`client_id` lookup).
2. Fetches the tenant's JWKS from `jwks_url` (cached for 5 minutes).
3. Verifies the JWT signature against the matching public key.

```bash
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/v1/scan
```

Error responses:
- `401 Unauthorized` – missing/invalid/expired token.
- `403 Forbidden` – valid token format but no matching tenant record.

On success the validated `TenantConfig` object is available as
`request.state.tenant` in all route handlers.

## Project Structure

```
fileguard/              Python package (FastAPI application)
├── main.py             Application entry point + middleware registration
├── config.py           Pydantic Settings configuration
├── api/
│   └── middleware/
│       ├── auth.py     Bearer-token authentication middleware
│       └── rate_limit.py Redis-backed sliding-window rate limiter
├── core/
│   ├── av_engine.py    Abstract AVEngineAdapter interface + ScanResult/Finding types
│   ├── clamav_adapter.py ClamAV clamd TCP socket adapter (fail-secure)
│   └── document_extractor.py  Multi-format text extractor with thread-pool execution
├── models/
│   ├── tenant_config.py  SQLAlchemy ORM model for tenant_config table
│   ├── scan_event.py     SQLAlchemy ORM model for scan_event table (append-only)
│   ├── batch_job.py      SQLAlchemy ORM model for batch_job table
│   └── compliance_report.py  SQLAlchemy ORM model for compliance_report table
├── schemas/
│   ├── tenant.py         Pydantic TenantConfig schema (request.state.tenant)
│   └── report.py         Pydantic schemas for compliance report data structures
├── celery_app.py         Celery application factory (broker, beat schedule)
├── services/
│   ├── audit.py          AuditService: HMAC-signed scan event persistence + SIEM forwarding
│   └── reports.py        ReportService + Celery tasks for compliance report generation
└── db/
    ├── base.py         Declarative base shared by all ORM models
    └── session.py      SQLAlchemy async session factory

docker/
├── Dockerfile          Multi-stage build (builder + slim runtime)
└── entrypoint.sh       Container startup script

migrations/             Alembic migration environment
├── env.py              Wired to Base.metadata for autogenerate support
├── script.py.mako
└── versions/           Migration scripts

tests/
├── conftest.py         Shared fixtures (env vars, DB session)
├── test_smoke.py       Smoke tests for FastAPI skeleton, config, Redis, DB session
├── unit/
│   ├── test_auth_middleware.py       Unit tests for auth middleware & schemas
│   ├── test_rate_limit.py            Unit tests for Redis rate limiting middleware
│   ├── test_clamav_adapter.py        Unit tests for ClamAV clamd adapter
│   ├── test_audit_service.py         Unit tests for AuditService (HMAC, SIEM, DB mock)
│   ├── test_document_extractor.py    Unit tests for DocumentExtractor
│   └── test_report_service.py        Unit tests for ReportService and Celery tasks
└── integration/
    └── test_audit_service_integration.py  Integration tests (SQLite + httpx transport)

docker-compose.yml      Local development compose file
requirements.txt        Python dependencies
alembic.ini             Alembic configuration
.dockerignore           Docker build context exclusions
```

## Compliance Reports

`fileguard/services/reports.py` implements scheduled compliance report generation.
See [`compliance-reports.md`](compliance-reports.md) for the full reference.

### Overview

| Component | Description |
|---|---|
| `fileguard/schemas/report.py` | Pydantic schemas: `VerdictBreakdown`, `ReportPayload`, `ComplianceReportCreate`, `ComplianceReportRead` |
| `fileguard/celery_app.py` | Celery app factory; Redis broker + result backend; configurable beat schedule |
| `fileguard/services/reports.py` | `ReportService` for aggregation + generation; Celery tasks for scheduling |

### Quick start

```python
from fileguard.services.reports import generate_compliance_report

# Trigger report generation for a single tenant asynchronously
generate_compliance_report.delay(
    tenant_id="<tenant-uuid>",
    period_start="2026-01-01T00:00:00+00:00",
    period_end="2026-02-01T00:00:00+00:00",
    fmt="json",  # or "pdf"
)
```

### Starting the Celery worker and beat scheduler

```bash
# Start the worker
celery -A fileguard.celery_app worker --loglevel=info -Q fileguard

# Start the beat scheduler (in a separate process)
celery -A fileguard.celery_app beat --loglevel=info
```

---

## AV Engine Adapter

FileGuard uses a plugin-based AV engine interface defined in `fileguard/core/av_engine.py`.
The default implementation is `ClamAVAdapter` (`fileguard/core/clamav_adapter.py`), which
communicates with a running `clamd` daemon over a TCP socket.

### Fail-Secure Behavior

Per ADR-06, the adapter implements **fail-secure** semantics: if the clamd daemon is
unreachable, times out, or returns an error, the scan result is `status: "rejected"` —
the file is **blocked**, not passed through.  This ensures a crashed or unavailable
AV engine cannot become a silent bypass.

### Usage

```python
from fileguard.core.clamav_adapter import ClamAVAdapter
from fileguard.config import settings

adapter = ClamAVAdapter(
    host=settings.CLAMAV_HOST,  # default: "clamav"
    port=settings.CLAMAV_PORT,  # default: 3310
)

# Scan a file on disk (requires shared filesystem between app and clamd)
result = await adapter.scan("/tmp/upload.pdf")

# Scan raw bytes (no shared filesystem required — preferred for containers)
result = await adapter.scan_bytes(file_bytes)

# Health check
is_available = await adapter.ping()

print(result.status)    # "clean" | "flagged" | "rejected"
print(result.findings)  # tuple of Finding(type, category, severity, match)
```

### Extending with Commercial Engines

To integrate a commercial AV engine (Sophos, CrowdStrike, etc.), subclass
`AVEngineAdapter` from `fileguard.core.av_engine` and implement the three abstract
methods (`scan`, `scan_bytes`, `ping`).  The fail-secure contract must be preserved:
all error paths must return `ScanResult(status="rejected", ...)` rather than raising.

## Document Extraction

`fileguard/core/document_extractor.py` provides the `DocumentExtractor` class
for multi-format text extraction used during the file scan pipeline.

### Supported formats

| Format        | MIME type                                                                    |
|---------------|------------------------------------------------------------------------------|
| PDF           | `application/pdf`                                                            |
| DOCX          | `application/vnd.openxmlformats-officedocument.wordprocessingml.document`    |
| CSV           | `text/csv`                                                                   |
| JSON          | `application/json`                                                           |
| Plain text    | `text/plain`                                                                 |
| ZIP (recursive) | `application/zip`                                                          |

### Thread-pool execution

All CPU-bound extraction is dispatched to a `ThreadPoolExecutor` via
`asyncio.get_running_loop().run_in_executor()`, keeping the asyncio event loop
unblocked.  The pool size is controlled by `THREAD_POOL_WORKERS` (default: 4).

### Usage

```python
from fileguard.core.document_extractor import DocumentExtractor

extractor = DocumentExtractor()          # uses settings.THREAD_POOL_WORKERS

result = await extractor.extract(file_bytes, "application/pdf")
print(result.text)                       # normalised text

for entry in result.offsets:
    span = result.text[entry.text_start:entry.text_end]
    print(f"bytes {entry.byte_start}–{entry.byte_end}: {span!r}")
```

### Error handling

`ExtractionError` is raised for unsupported MIME types or corrupt/malformed
files.  ZIP members that fail extraction are skipped with a warning log — one
corrupt member does not abort the whole archive.

## AuditService

`fileguard/services/audit.py` implements tamper-evident scan event logging:

- **HMAC-SHA256 signing** over canonical fields `(id, file_hash, status, action_taken, created_at)` using `SECRET_KEY`
- **Append-only persistence** — the `ScanEvent` model enforces no-UPDATE / no-DELETE at the application layer via SQLAlchemy event hooks
- **Best-effort SIEM forwarding** to Splunk (HEC) or RiverSafe WatchTower; delivery failures are logged and suppressed so they never block the scan pipeline

```python
from fileguard.services.audit import AuditService

service = AuditService(signing_key=settings.SECRET_KEY)
event = await service.log_scan_event(
    session=db_session,
    tenant_id=tenant.id,
    file_hash="abc123...",
    file_name="report.pdf",
    file_size_bytes=102400,
    mime_type="application/pdf",
    status="flagged",
    action_taken="quarantine",
    findings=[{"type": "pii", "category": "NHS_NUMBER", "severity": "high"}],
    scan_duration_ms=1240,
    siem_config=tenant.siem_config,  # optional
)
# Verify integrity later
assert service.verify_hmac(event)
```
