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

## Project Structure

```
fileguard/              Python package (FastAPI application)
├── main.py             Application entry point + health endpoint
├── config.py           Pydantic Settings configuration
└── db/
    └── session.py      SQLAlchemy async session factory

docker/
├── Dockerfile          Multi-stage build (builder + slim runtime)
└── entrypoint.sh       Container startup script

migrations/             Alembic migration environment
├── env.py
├── script.py.mako
└── versions/           Migration scripts

docker-compose.yml      Local development compose file
requirements.txt        Python dependencies
alembic.ini             Alembic configuration
.dockerignore           Docker build context exclusions
```
