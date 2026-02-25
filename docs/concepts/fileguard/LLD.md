The LLD has been written to `docs/concepts/fileguard/LLD.md`. Here is a summary of what each section covers:

**Section 1 — Implementation Overview:** Modular monolith in Python 3.12/FastAPI; `ScanContext` shared across composable pipeline steps; Celery for batch/webhooks; HMAC-signed PostgreSQL audit log; fail-secure by default.

**Section 2 — File Structure:** Full `fileguard/` directory tree covering API handlers, core pipeline modules, Celery workers, services (audit, SIEM, quarantine, reports), batch connectors, ORM models, Pydantic schemas, Alembic migrations, tests, Docker/Helm, and CLI.

**Section 3 — Component Designs:** Nine components with class layouts and inline pseudocode: `ScanPipeline`, `ScanContext`, `ClamAVAdapter`, `DocumentExtractor`, `PIIDetector`, `DispositionEngine`, `AuditService`, `BatchJobProcessor`, and `WebhookDispatcher`.

**Section 4 — Database Schema:** Full SQL for all four tables (`tenant_config`, `scan_event`, `batch_job`, `compliance_report`) with constraints, indexes, and append-only enforcement note.

**Section 5 — API Implementation:** Handler logic, validation rules, processing steps, and error codes for all five key endpoints.

**Section 6 — Function Signatures:** All public method signatures across every module with type annotations.

**Sections 7–12:** State management (stateless app + three external stores), error handling strategy (fail-secure + error code table), unit/integration/E2E test plans, green-field migration steps, rollback procedures per failure scenario, and performance optimisations (tmpfs, regex pre-compilation, thread pool for CPU-bound extraction, prefix partitioning, DB indexing).