"""Celery scan worker — async and batch file scanning via ScanPipeline.

This module wraps :class:`~fileguard.core.pipeline.ScanPipeline` in two
Celery tasks:

* :func:`scan_file_task` — scan a single file asynchronously.  Accepts
  base64-encoded file bytes so that the payload can be serialised cleanly
  over the JSON Celery transport.  Returns a structured disposition result
  dict.

* :func:`scan_batch_task` — fan out a list of file references to individual
  :func:`scan_file_task` subtasks and return a consolidated manifest.

Both tasks are routed to the ``fileguard`` queue and use exponential
back-off retries for transient failures (up to
:data:`_MAX_RETRIES` attempts).

**Retry policy**

Transient network errors (e.g. the ClamAV daemon being temporarily
unreachable or a database blip during the audit step) trigger an automatic
retry via :func:`celery.app.task.Task.retry`.  The countdown doubles after
each attempt:

* Attempt 1  — immediate
* Retry  1   — 2 s
* Retry  2   — 4 s
* Retry  3   — 8 s (max)

Non-transient pipeline failures (e.g. unsupported MIME type, corrupt file)
do *not* trigger retries; the final disposition is returned as ``"block"``
so the caller can take appropriate action.

**Pipeline construction**

The pipeline is built lazily inside each task invocation so that engine
configuration (ClamAV host/port, thread-pool size) is read from
:data:`~fileguard.config.settings` at the time the task runs rather than
at import time.  ClamAV is included only when ``settings.CLAMAV_HOST`` is
non-empty.

**Usage — single file**::

    from fileguard.workers.scan_worker import scan_file_task
    import base64

    file_b64 = base64.b64encode(open("document.pdf", "rb").read()).decode()
    result = scan_file_task.delay(
        file_bytes_b64=file_b64,
        mime_type="application/pdf",
        tenant_id="tenant-uuid",
    )
    print(result.get())  # {"scan_id": "...", "disposition": "pass", ...}

**Usage — batch**::

    from fileguard.workers.scan_worker import scan_batch_task

    items = [
        {"file_bytes_b64": base64.b64encode(b"...").decode(), "mime_type": "text/plain"},
        {"file_bytes_b64": base64.b64encode(b"...").decode(), "mime_type": "application/pdf"},
    ]
    result = scan_batch_task.delay(items=items, tenant_id="tenant-uuid")
    print(result.get())
    # {"total": 2, "results": [...], "summary": {"pass": 2, "block": 0, "quarantine": 0}}

**Starting a worker**::

    celery -A fileguard.celery_app worker --loglevel=info -Q fileguard
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import asdict
from typing import Any

from celery import group

from fileguard.celery_app import celery_app
from fileguard.config import settings
from fileguard.core.document_extractor import DocumentExtractor
from fileguard.core.pipeline import PipelineError, ScanPipeline
from fileguard.core.pii_detector import PIIDetector
from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum number of automatic retries for transient failures.
_MAX_RETRIES: int = 3

#: Base retry countdown in seconds; doubles on each successive attempt
#: (2 s, 4 s, 8 s).
_RETRY_BASE_SECONDS: int = 2

#: Exception types that trigger a retry.  Broad network / I/O categories
#: are included; ``PipelineError`` is deliberately excluded because it
#: indicates a scan-level failure (e.g. unsupported MIME, corrupt file)
#: that will not be resolved by retrying.
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_pipeline() -> ScanPipeline:
    """Construct a :class:`~fileguard.core.pipeline.ScanPipeline` from settings.

    DocumentExtractor and PIIDetector are always included.  ClamAV is
    added when ``settings.CLAMAV_HOST`` is non-empty, allowing the worker
    to operate in environments without a local ClamAV daemon (e.g. unit
    tests, development).

    Returns:
        A fully-configured :class:`~fileguard.core.pipeline.ScanPipeline`.
    """
    extractor = DocumentExtractor(max_workers=settings.THREAD_POOL_WORKERS)
    pii_detector = PIIDetector()

    av_engine = None
    if settings.CLAMAV_HOST:
        from fileguard.core.clamav_adapter import ClamAVAdapter
        av_engine = ClamAVAdapter(
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
        )

    return ScanPipeline(
        extractor=extractor,
        pii_detector=pii_detector,
        av_engine=av_engine,
    )


def _serialise_findings(findings: list[Any]) -> list[dict[str, Any]]:
    """Convert pipeline findings to JSON-serialisable dicts.

    Findings are :class:`~fileguard.core.pii_detector.PIIFinding` dataclass
    instances (or any object with ``type``, ``category``, ``severity``,
    ``match``, and ``offset`` attributes).  dataclass instances are
    converted via :func:`dataclasses.asdict`; other objects fall back to
    attribute extraction.

    Args:
        findings: Raw findings list from :attr:`~fileguard.core.scan_context.ScanContext.findings`.

    Returns:
        A list of plain ``dict`` objects suitable for JSON serialisation.
    """
    result: list[dict[str, Any]] = []
    for f in findings:
        try:
            result.append(asdict(f))  # type: ignore[arg-type]
        except TypeError:
            # Non-dataclass finding — extract common attributes manually.
            result.append(
                {
                    "type": getattr(f, "type", "unknown"),
                    "category": getattr(f, "category", ""),
                    "severity": getattr(f, "severity", ""),
                    "match": getattr(f, "match", ""),
                    "offset": getattr(f, "offset", 0),
                }
            )
    return result


def _build_scan_result(context: ScanContext) -> dict[str, Any]:
    """Build the structured result dict returned by :func:`scan_file_task`.

    Args:
        context: Completed (or partially-completed) :class:`~fileguard.core.scan_context.ScanContext`.

    Returns:
        Dict with keys ``scan_id``, ``disposition``, ``findings``,
        ``findings_count``, ``errors``, and ``metadata``.
    """
    return {
        "scan_id": context.scan_id,
        "disposition": context.metadata.get("disposition", "block"),
        "findings": _serialise_findings(context.findings),
        "findings_count": len(context.findings),
        "errors": context.errors,
        "metadata": {
            k: v
            for k, v in context.metadata.items()
            # Exclude large or non-serialisable values.
            if isinstance(v, (str, int, float, bool, list, dict, type(None)))
        },
    }


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="fileguard.workers.scan_worker.scan_file_task",
    bind=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def scan_file_task(
    self: Any,
    *,
    file_bytes_b64: str,
    mime_type: str,
    tenant_id: str | None = None,
    scan_id: str | None = None,
) -> dict[str, Any]:
    """Celery task: scan a single file through the FileGuard pipeline.

    Accepts base64-encoded file bytes so that binary payloads can be
    transported cleanly over the JSON Celery transport.  The pipeline is
    constructed fresh per invocation using the current
    :data:`~fileguard.config.settings`.

    On transient failure (network/IO errors) the task retries up to
    :data:`_MAX_RETRIES` times with exponential back-off
    (:data:`_RETRY_BASE_SECONDS` × 2^attempt seconds).

    On non-transient failure (corrupt file, unsupported MIME, etc.) the
    :class:`~fileguard.core.pipeline.PipelineError` is caught; the final
    result carries ``disposition="block"`` and the pipeline error details
    in ``errors``.

    Args:
        file_bytes_b64: Base64-encoded raw file bytes.
        mime_type: MIME type of the file (e.g. ``"application/pdf"``).
        tenant_id: Optional tenant UUID string for audit correlation.
        scan_id: Optional scan UUID string; auto-generated when omitted.

    Returns:
        A dict with:

        * ``scan_id``      — UUID of this scan.
        * ``disposition``  — ``"pass"``, ``"quarantine"``, or ``"block"``.
        * ``findings``     — list of serialised finding dicts.
        * ``findings_count`` — integer count of findings.
        * ``errors``       — list of error strings from failed pipeline steps.
        * ``metadata``     — dict of scan metadata (durations, AV status, …).

    Raises:
        :exc:`celery.exceptions.Retry`: On transient failure (up to
            :data:`_MAX_RETRIES` retries).
    """
    try:
        file_bytes = base64.b64decode(file_bytes_b64)
    except Exception as exc:
        logger.error("scan_file_task: failed to decode file_bytes_b64: %s", exc)
        return {
            "scan_id": scan_id or "",
            "disposition": "block",
            "findings": [],
            "findings_count": 0,
            "errors": [f"base64 decode error: {exc}"],
            "metadata": {},
        }

    context = ScanContext(
        file_bytes=file_bytes,
        mime_type=mime_type,
        tenant_id=tenant_id,
        **({"scan_id": scan_id} if scan_id else {}),
    )

    try:
        pipeline = _build_pipeline()
        asyncio.run(pipeline.run(context))

    except PipelineError as exc:
        # Non-transient pipeline failure: the context already has
        # disposition="block" and the error recorded.  Do not retry.
        logger.warning(
            "scan_file_task: pipeline failed at step '%s' (no retry): scan_id=%s error=%r",
            exc.step_name,
            context.scan_id,
            exc.original,
        )
        return _build_scan_result(context)

    except _TRANSIENT_EXCEPTIONS as exc:
        # Transient failure: retry with exponential back-off.
        countdown = _RETRY_BASE_SECONDS * (2 ** self.request.retries)
        logger.warning(
            "scan_file_task: transient error, retry %d/%d in %ds: scan_id=%s error=%r",
            self.request.retries + 1,
            _MAX_RETRIES,
            countdown,
            context.scan_id,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown)

    except Exception as exc:
        # Unexpected error: treat as transient to allow retries.
        countdown = _RETRY_BASE_SECONDS * (2 ** self.request.retries)
        logger.error(
            "scan_file_task: unexpected error, retry %d/%d in %ds: scan_id=%s error=%r",
            self.request.retries + 1,
            _MAX_RETRIES,
            countdown,
            context.scan_id,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown)

    logger.info(
        "scan_file_task: complete scan_id=%s disposition=%s findings=%d",
        context.scan_id,
        context.metadata.get("disposition"),
        len(context.findings),
    )
    return _build_scan_result(context)


@celery_app.task(
    name="fileguard.workers.scan_worker.scan_batch_task",
    bind=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def scan_batch_task(
    self: Any,
    *,
    items: list[dict[str, Any]],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Celery task: fan out a list of file references to individual scan tasks.

    Each entry in *items* is a dict with at least ``file_bytes_b64`` and
    ``mime_type`` keys.  An optional ``scan_id`` key is forwarded to the
    child :func:`scan_file_task`.

    Child tasks are dispatched as a Celery :class:`celery.group` and
    executed concurrently by available workers.  Results are collected
    synchronously (blocking until all subtasks complete) and consolidated
    into a summary manifest.

    Args:
        items: List of file reference dicts, each containing:

            * ``file_bytes_b64`` *(str, required)* — base64-encoded file bytes.
            * ``mime_type`` *(str, required)* — MIME type.
            * ``scan_id`` *(str, optional)* — explicit scan UUID.

        tenant_id: Optional tenant UUID string applied to all child scans.

    Returns:
        A dict with:

        * ``total``    — number of files submitted.
        * ``results``  — list of :func:`scan_file_task` result dicts, in the
          same order as *items*.
        * ``summary``  — aggregated disposition counts
          ``{"pass": N, "quarantine": N, "block": N}``.

    Raises:
        :exc:`celery.exceptions.Retry`: On transient dispatch errors.
    """
    if not items:
        return {
            "total": 0,
            "results": [],
            "summary": {"pass": 0, "quarantine": 0, "block": 0},
        }

    # Build the group of subtasks.
    subtasks = group(
        scan_file_task.s(
            file_bytes_b64=item["file_bytes_b64"],
            mime_type=item["mime_type"],
            tenant_id=tenant_id,
            scan_id=item.get("scan_id"),
        )
        for item in items
    )

    try:
        # apply_async() dispatches subtasks to the queue in production;
        # in eager mode (task_always_eager=True) it executes them
        # synchronously in-process, making this path correct for both.
        group_result = subtasks.apply_async()
        results: list[dict[str, Any]] = group_result.get(
            disable_sync_subtasks=True,  # allow .get() from within a task
            timeout=3600,  # 1-hour ceiling for large batches
        )
    except Exception as exc:
        countdown = _RETRY_BASE_SECONDS * (2 ** self.request.retries)
        logger.error(
            "scan_batch_task: dispatch error, retry %d/%d in %ds: error=%r",
            self.request.retries + 1,
            _MAX_RETRIES,
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown)

    # Aggregate disposition counts.
    summary: dict[str, int] = {"pass": 0, "quarantine": 0, "block": 0}
    for r in results:
        disposition = r.get("disposition", "block")
        summary[disposition] = summary.get(disposition, 0) + 1

    logger.info(
        "scan_batch_task: complete total=%d pass=%d quarantine=%d block=%d",
        len(results),
        summary["pass"],
        summary.get("quarantine", 0),
        summary["block"],
    )

    return {
        "total": len(results),
        "results": results,
        "summary": summary,
    }
