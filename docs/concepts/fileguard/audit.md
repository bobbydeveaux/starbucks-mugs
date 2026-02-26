# FileGuard Audit Service Reference

Documentation for the tamper-evident audit logging and SIEM forwarding service used by the FileGuard scan pipeline.

---

## Overview

`AuditService` provides HMAC-SHA256 integrity signing, append-only PostgreSQL persistence,
and optional real-time SIEM forwarding for every `ScanEvent` record produced by the scan pipeline.

**Design goals:**

| Goal | Implementation |
|---|---|
| Tamper detection | HMAC-SHA256 over immutable fields; verification fails if any signed field is mutated |
| Append-only | Service only issues `INSERT` (via `session.add` + `session.flush`); no `UPDATE`/`DELETE` code paths exist |
| Observability | Structured JSON log entry emitted on every successful audit call with `correlation_id`, `tenant_id`, and `scan_id` |
| Fail loud | `AuditError` is raised (never silently swallowed) on database write failure |
| SIEM integration | Scan events forwarded to Splunk HEC or RiverSafe WatchTower on a best-effort, fire-and-forget basis; SIEM failures never block scans |

---

## File

**`fileguard/services/audit.py`**

---

## Classes

### `AuditService`

```python
class AuditService:
    def __init__(
        self,
        secret_key: str | None = None,
        signing_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None: ...

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
        siem_config: dict[str, Any] | None = None,
    ) -> ScanEvent: ...
```

#### Constructor

| Argument | Type | Default | Description |
|---|---|---|---|
| `secret_key` | `str \| None` | `settings.SECRET_KEY` | HMAC signing secret. Must be kept confidential. |
| `signing_key` | `str \| None` | `None` | Alias for `secret_key`. Takes precedence when both are supplied. |
| `http_client` | `httpx.AsyncClient \| None` | `None` | Shared HTTP client for SIEM forwarding. When `None`, a transient client is created per forward call. Inject a shared client in production for connection pooling. |

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

#### `log_scan_event(session, scan_event, *, correlation_id, tenant_id, scan_id, siem_config)`

Computes the HMAC-SHA256 signature, writes it to `scan_event.hmac_signature`,
persists the record via `session.add()` + `session.flush()`, and optionally
forwards the event to a tenant-configured SIEM endpoint.

The caller controls the transaction lifecycle (`begin` / `commit` / `rollback`).
Multiple calls can be batched into a single transaction before committing.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `siem_config` | `dict \| None` | `None` | Tenant SIEM integration config. When `None`, SIEM forwarding is skipped. See [SIEM Configuration](#siem-configuration) for the expected schema. |

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

## SIEM forwarding

`AuditService` supports real-time, best-effort forwarding of scan events to a
tenant-configured SIEM endpoint. Forwarding is **fire-and-forget**: a 5-second HTTP
timeout is enforced and any delivery failure is logged at `WARNING` level and
suppressed — SIEM failures **never** disrupt the scan pipeline or cause transaction
rollbacks.

### Supported SIEM types

| Type value | SIEM system | Auth scheme | Payload format |
|---|---|---|---|
| `"splunk"` | Splunk HTTP Event Collector (HEC) | `Authorization: Splunk <token>` | `{"event": {...}, "sourcetype": "fileguard:scan"}` |
| `"watchtower"` | RiverSafe WatchTower REST API | `Authorization: Bearer <token>` | Flat event dict |

### SIEM configuration

The `siem_config` dict (stored as JSONB in the `tenant_config` table) has this schema:

```python
{
    "type": "splunk" | "watchtower",   # required
    "endpoint": "https://...",         # required — full URL of the SIEM ingest endpoint
    "token": "...",                    # optional — auth token
}
```

#### Splunk HEC example

```python
siem_config = {
    "type": "splunk",
    "endpoint": "https://splunk.example.com/services/collector/event",
    "token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
}
```

The forwarded payload follows the [Splunk HEC JSON format](https://docs.splunk.com/Documentation/Splunk/latest/Data/HECExamples):

```json
{
  "event": {
    "scan_id": "7c9e6679-...",
    "tenant_id": "d290f1ee-...",
    "file_hash": "e3b0c442...",
    "file_name": "upload.pdf",
    "file_size_bytes": 204800,
    "mime_type": "application/pdf",
    "status": "flagged",
    "action_taken": "quarantine",
    "findings": [{"type": "av_threat", "category": "Eicar-Test-Signature", "severity": "critical"}],
    "scan_duration_ms": 312,
    "created_at": "2026-02-26T10:15:30+00:00",
    "hmac_signature": "a1b2c3..."
  },
  "sourcetype": "fileguard:scan"
}
```

#### RiverSafe WatchTower example

```python
siem_config = {
    "type": "watchtower",
    "endpoint": "https://watchtower.example.com/api/v1/events",
    "token": "Bearer-token-here",
}
```

The forwarded payload is a flat event dict (no envelope):

```json
{
  "scan_id": "7c9e6679-...",
  "tenant_id": "d290f1ee-...",
  "file_hash": "e3b0c442...",
  "file_name": "upload.pdf",
  "file_size_bytes": 204800,
  "mime_type": "application/pdf",
  "status": "clean",
  "action_taken": "pass",
  "findings": [],
  "scan_duration_ms": 87,
  "created_at": "2026-02-26T10:15:30+00:00",
  "hmac_signature": "a1b2c3..."
}
```

### Failure modes

| Failure | Behaviour |
|---|---|
| Missing `endpoint` in config | Logs `WARNING "SIEM config missing 'endpoint'; skipping forwarding"`, returns |
| HTTP 4xx / 5xx | Logs `WARNING "SIEM delivery failed (HTTP <code>) for scan_id=..."`, returns |
| Network error (timeout, DNS, connection refused) | Logs `WARNING "SIEM delivery error for scan_id=..."`, returns |

In all failure cases the `log_scan_event()` call returns normally and the scan pipeline continues.

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

### Basic usage (no SIEM)

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

### With SIEM forwarding

```python
import httpx
from fileguard.services.audit import AuditService

# Inject a shared client for connection pooling (recommended in production)
http_client = httpx.AsyncClient()
audit = AuditService(http_client=http_client)

siem_config = {
    "type": "splunk",
    "endpoint": "https://splunk.example.com/services/collector/event",
    "token": "hec-token-here",
}

async def record_scan(scan_event: ScanEvent, tenant: TenantConfig, correlation_id: str) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await audit.log_scan_event(
                session,
                scan_event,
                correlation_id=correlation_id,
                tenant_id=tenant.id,
                scan_id=scan_event.id,
                siem_config=tenant.siem_config,  # None → forwarding skipped
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
- Splunk HEC payload wraps event in `{"event": {...}, "sourcetype": "fileguard:scan"}`
- WatchTower payload sends flat event dict
- Splunk auth header: `Authorization: Splunk <token>`
- WatchTower / generic auth header: `Authorization: Bearer <token>`
- SIEM HTTP errors and network errors logged at WARNING, never raised
- Missing SIEM endpoint logs warning and skips forwarding
- 5-second HTTP timeout enforced on all SIEM calls
