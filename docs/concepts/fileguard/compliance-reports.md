# FileGuard Compliance Reports Reference

Documentation for scheduled compliance report generation in the FileGuard service.

---

## Overview

FileGuard generates periodic compliance reports that summarise scan activity for each tenant.
Reports are produced as either **JSON** or **PDF** and stored to a configured output directory.
A `compliance_report` row is inserted into PostgreSQL on successful generation so that the
report can be retrieved later via the API.

Reports are driven by a **Celery beat task** that runs on a configurable cadence (daily or weekly).

---

## Files

| File | Purpose |
|---|---|
| `fileguard/schemas/report.py` | Pydantic validation schemas for report data structures |
| `fileguard/celery_app.py` | Celery application factory with broker configuration and beat schedule |
| `fileguard/services/reports.py` | `ReportService` class and Celery task definitions |

---

## Configuration

| Setting | Default | Description |
|---|---|---|
| `REDIS_URL` | _(required)_ | Redis URL used as Celery broker and result backend |
| `REPORTS_DIR` | `/tmp/fileguard/reports` | Filesystem directory where generated report files are stored |
| `REPORT_CADENCE` | `daily` | Beat schedule cadence — `"daily"` (24 h) or `"weekly"` (7 days) |

---

## Schemas (`fileguard/schemas/report.py`)

### `VerdictBreakdown`

Counts of scan events grouped by outcome for a report period.

```python
from fileguard.schemas.report import VerdictBreakdown

v = VerdictBreakdown(clean=90, flagged=7, rejected=3)
print(v.total)  # 100
```

| Field | Type | Description |
|---|---|---|
| `clean` | `int ≥ 0` | Events with status `"clean"` |
| `flagged` | `int ≥ 0` | Events with status `"flagged"` |
| `rejected` | `int ≥ 0` | Events with status `"rejected"` |
| `total` | `int` (property) | Sum of all three verdicts |

---

### `ReportPayload`

Full aggregated data payload for a generated compliance report.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | `UUID` | Tenant the report covers |
| `period_start` | `datetime` | Report period start (inclusive, timezone-aware) |
| `period_end` | `datetime` | Report period end (exclusive, timezone-aware) |
| `generated_at` | `datetime` | When the report was generated (UTC) |
| `file_count` | `int ≥ 0` | Total file scans in the period |
| `verdict_breakdown` | `VerdictBreakdown` | Per-verdict event counts |
| `pii_hits_by_category` | `dict[str, int]` | PII category → hit count (e.g. `{"NI_NUMBER": 5}`) |
| `top_file_types` | `dict[str, int]` | MIME type → scan count (up to 10 entries) |
| `average_scan_duration_ms` | `float ≥ 0` | Mean scan processing time in milliseconds |

**Validation:** `period_end` must be strictly after `period_start`.

---

### `ComplianceReportCreate`

Input schema for triggering report generation.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | `UUID` | Target tenant |
| `period_start` | `datetime` | Period start |
| `period_end` | `datetime` | Period end |
| `format` | `"json" \| "pdf"` | Output format (default: `"json"`) |

---

### `ComplianceReportRead`

Read schema for a `compliance_report` database row returned by API endpoints.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` | Report primary key |
| `tenant_id` | `UUID` | Report tenant |
| `period_start` | `datetime` | Period start |
| `period_end` | `datetime` | Period end |
| `format` | `str` | `"json"` or `"pdf"` |
| `file_uri` | `str` | URI where the file is stored (`file://...`) |
| `generated_at` | `datetime` | Generation timestamp |

---

## ReportService (`fileguard/services/reports.py`)

### `aggregate_metrics(session, tenant_id, period_start, period_end) → ReportPayload`

Queries `scan_event` records within the period and returns a fully-populated `ReportPayload`.

Queries performed (all filtered to `tenant_id` and `[period_start, period_end)`):

1. `COUNT(id)` → `file_count`
2. `GROUP BY status` → `verdict_breakdown`
3. `AVG(scan_duration_ms)` → `average_scan_duration_ms`
4. `GROUP BY mime_type LIMIT 10` → `top_file_types`
5. All `findings` JSONB values → `pii_hits_by_category` (aggregated in Python)

---

### `generate_json_report(payload) → bytes`

Serialises `payload` to indented UTF-8 JSON bytes.

---

### `generate_pdf_report(payload) → bytes`

Generates a ReportLab A4 PDF containing:

* Report title, period, generation timestamp, tenant ID
* Summary table: file count, per-verdict counts, average scan duration
* PII hits by category table (if any PII findings exist)
* Top file types table (if any scans were recorded)

Returns raw PDF bytes starting with the `%PDF` magic header.

---

### `store_report(content, fmt, tenant_id, period_start, period_end) → str`

Writes `content` to `settings.REPORTS_DIR` and returns a `file://` URI.

The filename format is:

```
report_<tenant_id>_<YYYYMMDD_start>_<YYYYMMDD_end>.<ext>
```

---

### `create_report_record(session, *, tenant_id, period_start, period_end, fmt, file_uri, generated_at) → ComplianceReport`

Inserts a `compliance_report` row and flushes within the caller's transaction.

---

### `generate_and_store(tenant_id, period_start, period_end, fmt) → ComplianceReport`

End-to-end orchestration: opens a new database session, calls `aggregate_metrics`,
generates the report file, stores it, inserts the `compliance_report` row, and
emits a structured log entry.

```python
from fileguard.services.reports import ReportService
from datetime import datetime, timezone

service = ReportService()
report = await service.generate_and_store(
    tenant_id=uuid.UUID("..."),
    period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
    fmt="json",
)
print(report.file_uri)   # file:///tmp/fileguard/reports/report_<id>_20260101_20260201.json
```

---

## Celery Application (`fileguard/celery_app.py`)

The Celery app uses Redis as both broker and result backend.

```python
from fileguard.celery_app import celery_app
```

### Beat schedule

The `generate-scheduled-compliance-reports` beat entry calls
`fileguard.services.reports.generate_scheduled_reports` on the configured cadence:

| `REPORT_CADENCE` | Interval |
|---|---|
| `daily` (default) | Every 24 hours |
| `weekly` | Every 7 days |

---

## Celery Tasks

### `generate_compliance_report`

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_compliance_report(self, tenant_id, period_start, period_end, fmt="json"):
    ...
```

Generates a compliance report for a single tenant/period.

| Parameter | Type | Description |
|---|---|---|
| `tenant_id` | `str` | Tenant UUID as ISO string |
| `period_start` | `str` | ISO-8601 period start |
| `period_end` | `str` | ISO-8601 period end |
| `fmt` | `str` | `"json"` (default) or `"pdf"` |

Returns `{"report_id": "<uuid>", "file_uri": "<uri>"}` on success.
Retries up to 3 times on transient failure (60 s delay between attempts).

---

### `generate_scheduled_reports`

Beat task.  Determines the previous reporting period based on `REPORT_CADENCE`,
queries all tenant IDs, and fans out one `generate_compliance_report` task per
tenant per format (JSON + PDF).

Returns `{"tenants_processed": N, "period": {"start": "...", "end": "..."}}`.

---

## Starting Workers

```bash
# Install dependencies
pip install -e ".[dev]"

# Start the worker
celery -A fileguard.celery_app worker --loglevel=info -Q fileguard

# Start the beat scheduler (separate process)
celery -A fileguard.celery_app beat --loglevel=info
```

---

## Running Tests

```bash
pytest tests/unit/test_report_service.py -v
```

All tests are fully offline — database access and file I/O are replaced by
`unittest.mock` patches.

Test coverage includes:

* Schema field validation and cross-field constraints
* `aggregate_metrics` database query results and PII aggregation
* `generate_json_report` output structure and JSON correctness
* `generate_pdf_report` PDF magic header and error-free generation
* `store_report` filesystem writes and URI format
* `create_report_record` ORM INSERT
* `generate_and_store` end-to-end orchestration
* Celery task delegation and retry behaviour
* Beat task fan-out and period calculation
