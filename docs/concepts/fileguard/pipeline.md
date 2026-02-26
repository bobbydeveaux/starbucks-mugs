# ScanPipeline — FileGuard Scan Orchestrator

`fileguard/core/pipeline.py`

## Overview

`ScanPipeline` orchestrates the six-step file scanning process in the FileGuard system.  Each step mutates a shared `ScanContext` object in place, and every step is wrapped in a named OpenTelemetry (OTel) trace span to provide full pipeline observability.

## Pipeline Steps

The pipeline executes the following steps **in order**:

| # | Step | Module | Description |
|---|------|--------|-------------|
| 1 | `extract` | `document_extractor.py` | Convert raw file bytes to normalised text + byte offsets |
| 2 | `av_scan` | AV engine adapter | Scan for malware threats using the configured AV engine |
| 3 | `pii_detect` | `pii_detector.py` | Detect PII patterns (NI, NHS, email, phone, postcode, …) in extracted text |
| 4 | `redact` | Redaction engine | Replace matched PII spans with `[REDACTED]` tokens (optional) |
| 5 | `disposition` | Disposition engine | Evaluate all findings and determine action: `pass`, `quarantine`, or `block` |
| 6 | `audit` | Audit callable | Persist the `ScanEvent` to the append-only audit log (optional) |

## Fail-Secure Contract

Any uncaught exception in any step immediately:

1. Halts the pipeline (no subsequent steps run).
2. Sets `context.metadata["disposition"] = "block"`.
3. Sets `context.metadata["pipeline_failed"] = True`.
4. Appends a structured error string to `context.errors`.
5. Re-raises a `PipelineError` so the caller can apply fail-safe disposition.

The `ScanContext` object is always in a consistent (though potentially partial) state after a `PipelineError`.

## OpenTelemetry Instrumentation

- A root span `fileguard.scan` is opened for the entire pipeline run.
- Each step opens a child span `fileguard.<step_name>` (e.g. `fileguard.extract`, `fileguard.av_scan`).
- Span attributes include `scan.id`, `scan.tenant_id`, `scan.mime_type`, `scan.file_size_bytes`, `scan.disposition`, `scan.findings_count`, `scan.duration_ms`, and `step.duration_ms`.
- On failure: `scan.pipeline_failed`, `scan.failed_step`, and the exception are recorded on the root span.

## Constructor

```python
ScanPipeline(
    *,
    extractor: DocumentExtractor,        # required
    pii_detector: PIIDetector,           # required
    av_engine: AVEngineAdapterProtocol | None = None,
    redaction_engine: RedactionEngineProtocol | None = None,
    disposition_engine: DispositionEngineProtocol | None = None,
    audit_callable: AsyncCallable | None = None,
)
```

Optional engines are cleanly skipped when `None`.

## ScanContext Metadata Keys

After a successful run, `context.metadata` contains:

| Key | Type | Description |
|-----|------|-------------|
| `extracted_chars` | `int` | Number of characters extracted from the document |
| `av_status` | `str` | AV result: `"clean"`, `"flagged"`, or `"rejected"` |
| `av_engine` | `str` | Engine name (e.g. `"clamav"`) |
| `av_duration_ms` | `int` | Time taken by the AV scan in ms |
| `av_threats` | `list[str]` | Threat names (populated only when `av_status == "flagged"`) |
| `pii_findings_count` | `int` | Count of PII-type findings in `context.findings` |
| `disposition` | `str` | Final action: `"pass"`, `"quarantine"`, or `"block"` |
| `scan_duration_ms` | `int` | Total wall-clock time for the pipeline run in ms |
| `pipeline_failed` | `bool` | `True` only when a step raised an exception |

## Default Disposition Rules

When no `disposition_engine` is configured, the built-in rules apply:

- `"block"` — if AV status is `"flagged"` or any `av_threat` finding is present.
- `"pass"` — for all other outcomes (clean AV, PII-only findings, or no AV engine).

To quarantine PII-flagged files, inject a custom `DispositionEngineProtocol`.

## Custom Protocols

The pipeline accepts duck-typed engines through runtime-checkable protocols:

```python
class RedactionEngineProtocol(Protocol):
    def redact(self, context: ScanContext) -> None: ...

class DispositionEngineProtocol(Protocol):
    def evaluate(self, context: ScanContext) -> str: ...

class AVEngineAdapterProtocol(Protocol):
    async def scan_bytes(self, data: bytes) -> ScanResult: ...
```

## Exceptions

| Exception | Raised by | Meaning |
|-----------|-----------|---------|
| `PipelineError` | `_run_step()` | Wraps any step exception; carries `step_name` and `original` |
| `AVScanRejectedError` | `_step_av_scan()` | AV engine returned `status="rejected"` (engine failure) |

## Usage Examples

### Minimal pipeline (development, no AV daemon)

```python
from fileguard.core.pipeline import ScanPipeline
from fileguard.core.document_extractor import DocumentExtractor
from fileguard.core.pii_detector import PIIDetector
from fileguard.core.scan_context import ScanContext

pipeline = ScanPipeline(
    extractor=DocumentExtractor(max_workers=2),
    pii_detector=PIIDetector(),
)

context = ScanContext(file_bytes=raw_bytes, mime_type="application/pdf")
await pipeline.run(context)

print(context.metadata["disposition"])    # "pass"
print(context.metadata["pii_findings_count"])  # 0
```

### Full pipeline with ClamAV and audit

```python
from fileguard.core.clamav_adapter import ClamAVAdapter
from fileguard.core.pipeline import PipelineError, ScanPipeline
from fileguard.core.document_extractor import DocumentExtractor
from fileguard.core.pii_detector import PIIDetector
from fileguard.core.scan_context import ScanContext

pipeline = ScanPipeline(
    extractor=DocumentExtractor(),
    pii_detector=PIIDetector(),
    av_engine=ClamAVAdapter(host="clamav", port=3310),
    audit_callable=my_audit_fn,
)

context = ScanContext(
    file_bytes=raw_bytes,
    mime_type="application/pdf",
    tenant_id="tenant-uuid",
)

try:
    await pipeline.run(context)
except PipelineError as exc:
    # context.metadata["disposition"] == "block" guaranteed
    logger.error("Scan failed at step %s: %s", exc.step_name, exc.original)

disposition = context.metadata["disposition"]  # "pass", "quarantine", or "block"
```

## Async and Batch Execution

For asynchronous and batch invocation of the pipeline via Celery, see the
[Scan Worker documentation](scan-worker.md).  `scan_file_task` wraps a single
pipeline run; `scan_batch_task` fans out multiple files in parallel.

## Tests

Integration tests are in `fileguard/tests/test_pipeline.py` and cover:

- Happy path: clean file with clean AV → `"pass"` disposition.
- AV threat: `"flagged"` result → `"block"` disposition.
- AV rejected (engine failure): `PipelineError` raised + `"block"` disposition.
- Mid-pipeline failure (extraction, PII detect, disposition, audit): `PipelineError` raised, context errors populated.
- Partial state preserved: steps completed before failure retain their results.
- Optional steps: correctly skipped when not configured.
- Redaction and audit callables: invoked when configured.
- Custom disposition engine: result overrides built-in default.
- Step ordering: each step sees the results of all prior steps.
