# Celery Scan Worker — Async and Batch File Scanning

`fileguard/workers/scan_worker.py`

## Overview

The scan worker wraps :class:`~fileguard.core.pipeline.ScanPipeline` in two
Celery tasks that enable **asynchronous single-file scanning** and
**parallel batch fan-out** without blocking the FastAPI HTTP layer.

Both tasks are routed to the `fileguard` queue and configured with
`acks_late=True` and `reject_on_worker_lost=True` for at-least-once delivery
semantics.

---

## Tasks

### `scan_file_task`

**Task name:** `fileguard.workers.scan_worker.scan_file_task`

Scans a single file through the full `ScanPipeline` (extract → AV scan →
PII detect → redact → disposition → audit).

**Parameters** (keyword-only):

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_bytes_b64` | `str` | Yes | Base64-encoded raw file bytes |
| `mime_type` | `str` | Yes | MIME type (e.g. `"application/pdf"`) |
| `tenant_id` | `str \| None` | No | Tenant UUID string for audit correlation |
| `scan_id` | `str \| None` | No | Explicit scan UUID (auto-generated when absent) |

**Return value:**

```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "disposition": "pass",
  "findings": [],
  "findings_count": 0,
  "errors": [],
  "metadata": {
    "disposition": "pass",
    "extracted_chars": 1234,
    "av_status": "clean",
    "av_engine": "clamav",
    "av_duration_ms": 42,
    "pii_findings_count": 0,
    "scan_duration_ms": 150
  }
}
```

`disposition` is one of `"pass"`, `"quarantine"`, or `"block"`.

### `scan_batch_task`

**Task name:** `fileguard.workers.scan_worker.scan_batch_task`

Fans out a list of file references to individual `scan_file_task` subtasks
using a Celery `group`, then aggregates the results into a consolidated
manifest.

**Parameters** (keyword-only):

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `items` | `list[dict]` | Yes | List of file reference dicts (see below) |
| `tenant_id` | `str \| None` | No | Tenant UUID applied to all child scans |

Each item in `items` must have:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `file_bytes_b64` | `str` | Yes | Base64-encoded file bytes |
| `mime_type` | `str` | Yes | MIME type |
| `scan_id` | `str` | No | Explicit scan UUID for this item |

**Return value:**

```json
{
  "total": 3,
  "results": [
    {"scan_id": "...", "disposition": "pass", ...},
    {"scan_id": "...", "disposition": "pass", ...},
    {"scan_id": "...", "disposition": "block", ...}
  ],
  "summary": {
    "pass": 2,
    "quarantine": 0,
    "block": 1
  }
}
```

---

## Retry Policy

Both tasks retry transient failures with exponential back-off:

| Attempt | Countdown |
|---------|-----------|
| Initial | immediate |
| Retry 1 | 2 s |
| Retry 2 | 4 s |
| Retry 3 | 8 s |

**Transient errors** (retried): `ConnectionError`, `TimeoutError`, `OSError`,
and any other unexpected exception.

**Non-transient errors** (not retried): `PipelineError` — indicates a
scan-level failure (corrupt file, unsupported MIME type, AV engine rejection).
The task returns a result with `disposition="block"` so callers can take
fail-safe action.

---

## Pipeline Construction

The pipeline is built lazily inside each task invocation so that engine
configuration is read from `settings` at task execution time:

- `DocumentExtractor` — always included.
- `PIIDetector` — always included.
- `ClamAVAdapter` — included only when `settings.CLAMAV_HOST` is non-empty.
  This allows the worker to operate in development/test environments without
  a running ClamAV daemon.

---

## Usage Examples

### Single file (Python API)

```python
import base64
from fileguard.workers.scan_worker import scan_file_task

with open("document.pdf", "rb") as f:
    file_b64 = base64.b64encode(f.read()).decode()

result = scan_file_task.delay(
    file_bytes_b64=file_b64,
    mime_type="application/pdf",
    tenant_id="550e8400-e29b-41d4-a716-446655440000",
)
outcome = result.get(timeout=60)
print(outcome["disposition"])  # "pass", "quarantine", or "block"
```

### Batch submission (Python API)

```python
import base64
from fileguard.workers.scan_worker import scan_batch_task

items = [
    {
        "file_bytes_b64": base64.b64encode(open("doc1.pdf", "rb").read()).decode(),
        "mime_type": "application/pdf",
    },
    {
        "file_bytes_b64": base64.b64encode(open("doc2.docx", "rb").read()).decode(),
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
]

result = scan_batch_task.delay(
    items=items,
    tenant_id="550e8400-e29b-41d4-a716-446655440000",
)
manifest = result.get(timeout=300)
print(manifest["summary"])  # {"pass": 2, "quarantine": 0, "block": 0}
```

### Starting a worker

```bash
# Start a scan worker consuming the 'fileguard' queue
celery -A fileguard.celery_app worker --loglevel=info -Q fileguard

# Start with concurrency 4
celery -A fileguard.celery_app worker --loglevel=info -Q fileguard --concurrency=4
```

---

## File Reference Transport

Binary file bytes are transmitted as **base64-encoded strings** so that the
Celery JSON serialiser can carry them without binary-safe encoding overhead.
Callers must encode bytes before submission and the worker decodes them
transparently.

If the `file_bytes_b64` value cannot be decoded (malformed base64), the task
immediately returns `disposition="block"` without retrying.

---

## Celery App Registration

The workers module is registered in `fileguard/celery_app.py`:

```python
celery_app = Celery(
    "fileguard",
    include=[
        "fileguard.services.reports",
        "fileguard.workers.scan_worker",   # ← scan worker tasks
    ],
)
```

---

## Tests

Integration tests are in `fileguard/tests/test_scan_worker.py` and run in
**Celery eager mode** (`task_always_eager=True`) — no broker or worker
process is required.

Coverage:

- Happy path: clean file → `"pass"` disposition, correct result structure.
- AV threat: flagged scan → `"block"` disposition, findings serialised.
- PII findings: `PIIFinding` dataclass serialised to dict in result.
- Invalid base64: immediate `"block"`, error populated in result.
- Pipeline error (extraction failure): `"block"`, no retry triggered.
- Transient error: `ConnectionError` retried 3× before exhaustion.
- Batch: empty list, single item, multiple items, mixed dispositions, summary counts.
- Task registration: both tasks present in `celery_app.tasks` registry.
