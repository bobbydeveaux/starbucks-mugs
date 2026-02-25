# FileGuard Audit Service Reference

Documentation for the tamper-evident audit logging service used by the FileGuard scan pipeline.

---

## Overview

`AuditService` provides HMAC-SHA256 integrity signing and append-only PostgreSQL persistence
for every `ScanEvent` record produced by the scan pipeline.

**Design goals:**

| Goal | Implementation |
|---|---|
| Tamper detection | HMAC-SHA256 over immutable fields; verification fails if any signed field is mutated |
| Append-only | Service only issues `INSERT` (via `session.add` + `session.flush`); no `UPDATE`/`DELETE` code paths exist |
| Observability | Structured JSON log entry emitted on every successful audit call with `correlation_id`, `tenant_id`, and `scan_id` |
| Fail loud | `AuditError` is raised (never silently swallowed) on database write failure |

---

## File

**`fileguard/services/audit.py`**

---

## Classes

### `AuditService`

```python
class AuditService:
    def __init__(self, secret_key: str | None = None) -> None: ...
    def compute_hmac(self, scan_event: ScanEvent) -> str: ...
    def verify_hmac(self, scan_event: ScanEvent) -> bool: ...
    async def log_scan_event(
        self,
        session: AsyncSession,
        scan_event: ScanEvent,
        *,
        correlation_id: str | uuid.UUID | None = None,
        tenant_id: str | uuid.UUID | None = None,
        scan_id: str | uuid.UUID | None = None,
    ) -> ScanEvent: ...
```

#### Constructor

| Argument | Type | Default | Description |
|---|---|---|---|
| `secret_key` | `str \| None` | `settings.SECRET_KEY` | HMAC signing secret. Must be kept confidential. |

#### `compute_hmac(scan_event)`

Computes HMAC-SHA256 over the canonical immutable fields of a `ScanEvent`.

**Signed fields (in order):**

```
{id}|{file_hash}|{status}|{action_taken}|{created_at}
```

Fields are pipe-separated (`|`) to prevent boundary-confusion attacks.
`created_at` is serialised as ISO-8601 with UTC offset for unambiguous cross-timezone
representation.

**Returns:** 64-character lowercase hex string.

#### `verify_hmac(scan_event)`

Verifies that `scan_event.hmac_signature` matches the HMAC-SHA256 computed over
the current field values. Uses `hmac.compare_digest` to prevent timing attacks.

**Returns:** `True` if valid, `False` if the record has been tampered with or the
signature is empty/invalid.

#### `log_scan_event(session, scan_event, *, correlation_id, tenant_id, scan_id)`

Computes the HMAC-SHA256 signature, writes it to `scan_event.hmac_signature`, and
persists the record via `session.add()` + `session.flush()`.

The caller controls the transaction lifecycle (`begin` / `commit` / `rollback`).
Multiple calls can be batched into a single transaction before committing.

**Returns:** The same `scan_event` instance with `hmac_signature` populated.

**Raises:** `AuditError` if the database INSERT fails for any reason.

---

### `AuditError`

```python
class AuditError(Exception): ...
```

Raised by `log_scan_event()` when the INSERT cannot be completed. Always chains
the original database exception as `__cause__` for root-cause analysis.

Callers must **not** silently ignore this exception. The scan pipeline should treat
an audit write failure as a hard error.

---

## Signed fields

The following `ScanEvent` fields are included in the HMAC-SHA256 computation.
Any mutation to these fields after insertion will cause `verify_hmac()` to return `False`.

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key — serialised with `str()` |
| `file_hash` | `str` | SHA-256 digest of the scanned file content |
| `status` | `str` | `"clean"`, `"flagged"`, or `"rejected"` |
| `action_taken` | `str` | `"pass"`, `"quarantine"`, or `"block"` |
| `created_at` | `datetime` | Serialised as ISO-8601 string with UTC offset |

Fields **not** included in the HMAC (intentionally mutable or secondary metadata):
`file_name`, `file_size_bytes`, `mime_type`, `findings`, `scan_duration_ms`, `tenant_id`.

---

## Structured log output

On every successful `log_scan_event()` call, a JSON-structured log entry is emitted
at `INFO` level via the `fileguard.services.audit` logger:

```json
{
  "event": "scan_event_audited",
  "correlation_id": "req-abc123",
  "tenant_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "scan_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "file_hash": "e3b0c44298fc1c149afb...",
  "status": "clean",
  "action_taken": "pass"
}
```

| Field | Fallback when omitted |
|---|---|
| `correlation_id` | `null` |
| `tenant_id` | `scan_event.tenant_id` |
| `scan_id` | `scan_event.id` |

Log aggregation systems (Splunk, Elasticsearch, Loki) can index on
`correlation_id` to trace a single request across all services, and on `tenant_id`
to produce per-tenant audit reports.

---

## Database persistence

`AuditService` persists records to the `scan_event` PostgreSQL table (defined in
migration `0001_initial_schema.py`).

**Append-only guarantees operate at two layers:**

| Layer | Mechanism |
|---|---|
| Application | `AuditService.log_scan_event()` only calls `session.add()` — no `UPDATE`/`DELETE` code paths exist |
| SQLAlchemy ORM | `before_update` and `before_delete` event listeners on `ScanEvent` raise `RuntimeError` |
| PostgreSQL | `tg_scan_event_append_only` trigger raises an exception for any `UPDATE` or `DELETE` on `scan_event` |

All three layers must be bypassed simultaneously for a record to be tampered with
undetected. The HMAC signature provides a fourth, cryptographic layer of assurance.

---

## Usage

### Basic usage

```python
from fileguard.db.session import AsyncSessionLocal
from fileguard.models.scan_event import ScanEvent
from fileguard.services.audit import AuditService

audit = AuditService()  # defaults to settings.SECRET_KEY

async def record_scan(scan_event: ScanEvent, correlation_id: str) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await audit.log_scan_event(
                session,
                scan_event,
                correlation_id=correlation_id,
                tenant_id=scan_event.tenant_id,
                scan_id=scan_event.id,
            )
```

### Verifying integrity post-insert

```python
is_valid = audit.verify_hmac(fetched_scan_event)
if not is_valid:
    raise RuntimeError(f"Tampered audit record detected: {fetched_scan_event.id}")
```

### Error handling

```python
from fileguard.services.audit import AuditError

try:
    await audit.log_scan_event(session, scan_event, correlation_id=corr_id)
except AuditError as exc:
    logger.critical("Audit write failed: %s", exc)
    raise  # propagate — never swallow
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/unit/test_audit_service.py -v
```

Tests are fully offline (no PostgreSQL or Redis required). Coverage includes:

- HMAC determinism and sensitivity to each signed field
- Tampered record detection for every signed field
- Append-only enforcement (only `session.add` + `session.flush` called; no UPDATE/DELETE)
- HMAC signature set on event before INSERT
- Structured log output with all required fields (`correlation_id`, `tenant_id`, `scan_id`)
- Fallback values when kwargs are omitted
- `AuditError` raised and chained on DB write failure
- No log emitted when INSERT fails
