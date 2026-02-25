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
│       └── auth.py     Bearer-token authentication middleware
├── core/
│   └── document_extractor.py  Multi-format text extractor with byte-offset mapping
├── models/
│   └── tenant_config.py SQLAlchemy ORM model for tenant_config table
├── schemas/
│   └── tenant.py       Pydantic TenantConfig schema (request.state.tenant)
└── db/
    └── session.py      SQLAlchemy async session factory

docker/
├── Dockerfile          Multi-stage build (builder + slim runtime)
└── entrypoint.sh       Container startup script

migrations/             Alembic migration environment
├── env.py              Wired to Base.metadata for autogenerate support
├── script.py.mako
└── versions/           Migration scripts

tests/
└── unit/
    ├── test_auth_middleware.py  Unit tests for auth middleware & schemas
    └── test_document_extractor.py  Unit tests for DocumentExtractor

docker-compose.yml      Local development compose file
requirements.txt        Python dependencies
alembic.ini             Alembic configuration
.dockerignore           Docker build context exclusions
```

## DocumentExtractor

`fileguard/core/document_extractor.py` provides text extraction from six document formats with a byte-offset map for PII span localisation.

### Supported formats

| Format | MIME type | Library |
|---|---|---|
| PDF | `application/pdf` | pdfminer.six |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | python-docx |
| CSV | `text/csv` | stdlib `csv` |
| JSON | `application/json` | stdlib `json` |
| TXT | `text/plain` | built-in decode |
| ZIP | `application/zip` | stdlib `zipfile` (recursive) |

### Usage

```python
from fileguard.core.document_extractor import DocumentExtractor

with DocumentExtractor(thread_pool_workers=4) as extractor:
    result = extractor.extract(pdf_bytes, "report.pdf")
    print(result.text)
    for offset in result.offsets:
        # offset.char_start / offset.char_end index into result.text
        # offset.byte_start / offset.byte_end reference the original file bytes
        span = result.text[offset.char_start:offset.char_end]
```

### ExtractionResult

| Field | Type | Description |
|---|---|---|
| `text` | `str` | Normalised Unicode text concatenated across all content |
| `offsets` | `list[ByteOffset]` | Ordered list mapping text character spans to original byte ranges |

### ByteOffset

| Field | Type | Description |
|---|---|---|
| `char_start` | `int` | Inclusive start character index in `ExtractionResult.text` |
| `char_end` | `int` | Exclusive end character index in `ExtractionResult.text` |
| `byte_start` | `int` | Inclusive start byte offset in the original file data |
| `byte_end` | `int` | Exclusive end byte offset in the original file data |

### Exceptions

| Exception | When raised |
|---|---|
| `UnsupportedMIMETypeError` | File MIME type is not in the supported list |
| `CorruptFileError` | File cannot be parsed (malformed PDF, invalid ZIP, non-JSON bytes, etc.) |

Both exceptions extend `DocumentExtractorError`.

### ZIP safety limits

| Parameter | Default | Description |
|---|---|---|
| `max_zip_depth` | 2 | Maximum recursive nesting depth |
| `max_zip_files` | 1 000 | Maximum files processed per archive |

Entries that exceed the depth limit or whose MIME type is unsupported are silently skipped; the archive as a whole still yields results from valid entries.
