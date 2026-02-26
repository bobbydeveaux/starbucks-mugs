"""ScanPipeline — orchestration of the FileGuard scan pipeline with OpenTelemetry instrumentation.

:class:`ScanPipeline` coordinates the six pipeline steps in order:

1. **extract**     — convert raw bytes to normalised text via :class:`~fileguard.core.document_extractor.DocumentExtractor`
2. **av_scan**     — scan for malware via an :class:`~fileguard.core.av_engine.AVEngineAdapter` implementation
3. **pii_detect**  — detect PII patterns via :class:`~fileguard.core.pii_detector.PIIDetector`
4. **redact**      — replace PII spans with ``[REDACTED]`` tokens (optional)
5. **disposition** — evaluate findings and determine the action (optional)
6. **audit**       — persist the scan result to the append-only audit log (optional)

Each step mutates :class:`~fileguard.core.scan_context.ScanContext` in place.
Every step is wrapped in a named OpenTelemetry trace span so that distributed
traces show the full pipeline execution tree with per-step timing.

**Fail-secure contract**: any uncaught exception in any step immediately halts
the pipeline, sets ``context.metadata["disposition"]`` to ``"block"``, appends a
structured error string to ``context.errors``, and re-raises a
:class:`PipelineError` so the caller can apply fail-safe disposition.  The
context object is always in a consistent (though potentially partial) state after
a :class:`PipelineError` is raised.

Usage::

    from fileguard.core.pipeline import ScanPipeline
    from fileguard.core.document_extractor import DocumentExtractor
    from fileguard.core.pii_detector import PIIDetector
    from fileguard.core.scan_context import ScanContext

    pipeline = ScanPipeline(
        extractor=DocumentExtractor(),
        pii_detector=PIIDetector(),
    )
    context = ScanContext(file_bytes=raw_bytes, mime_type="application/pdf")
    try:
        await pipeline.run(context)
    except PipelineError:
        # context.metadata["disposition"] is already "block"
        pass
    print(context.metadata["disposition"])  # "pass", "block", etc.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from fileguard.core.document_extractor import DocumentExtractor
from fileguard.core.pii_detector import PIIDetector
from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)

# OTel tracer — one per module, reused across all pipeline executions.
tracer = trace.get_tracer(
    "fileguard.pipeline",
    schema_url="https://opentelemetry.io/schemas/1.11.0",
)

# Disposition applied whenever a pipeline step fails (fail-secure).
_FAIL_SECURE_DISPOSITION = "block"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Raised when a pipeline step fails unrecoverably.

    Wraps the original exception to identify which step failed while
    preserving the full cause chain via ``__cause__``.

    Attributes:
        step_name: Short name of the step that raised (e.g. ``"extract"``).
        original: The exception that triggered the pipeline failure.
    """

    def __init__(self, step_name: str, original: Exception) -> None:
        super().__init__(f"Pipeline step '{step_name}' failed: {original}")
        self.step_name = step_name
        self.original = original


class AVScanRejectedError(Exception):
    """Raised by the ``av_scan`` step when the AV engine rejects the scan.

    Per the fail-secure contract, an engine rejection (connection failure,
    timeout, or unexpected engine response) must never silently pass a file
    through.  This exception triggers :class:`PipelineError` handling in
    :meth:`ScanPipeline.run`, which sets disposition to ``"block"``.
    """


# ---------------------------------------------------------------------------
# Optional engine protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class RedactionEngineProtocol(Protocol):
    """Minimal interface expected by the ``redact`` pipeline step.

    Any object with a ``redact(context)`` method is accepted — no base class
    inheritance is required.
    """

    def redact(self, context: ScanContext) -> None:
        """Replace PII spans in *context* with ``[REDACTED]`` tokens.

        Mutates *context* in place.  Results are typically written to
        ``context.metadata["redacted_text"]`` or similar.

        Args:
            context: The shared scan context for the current scan.
        """
        ...


@runtime_checkable
class DispositionEngineProtocol(Protocol):
    """Minimal interface expected by the ``disposition`` pipeline step.

    Any object with an ``evaluate(context)`` method is accepted.
    """

    def evaluate(self, context: ScanContext) -> str:
        """Evaluate findings in *context* and return a disposition string.

        Args:
            context: The shared scan context, including all findings from
                prior pipeline steps.

        Returns:
            One of ``"pass"``, ``"quarantine"``, or ``"block"``.
        """
        ...


@runtime_checkable
class AVEngineAdapterProtocol(Protocol):
    """Minimal async interface expected by the ``av_scan`` pipeline step."""

    async def scan_bytes(self, data: bytes) -> Any:
        """Scan *data* for malware and return a result object.

        The result object must have:
        - ``status``: ``"clean"``, ``"flagged"``, or ``"rejected"``
        - ``findings``: iterable of finding objects
        - ``engine``: engine name string
        - ``duration_ms``: int milliseconds

        Args:
            data: Raw file bytes to scan.

        Returns:
            An AV scan result object.
        """
        ...


# ---------------------------------------------------------------------------
# ScanPipeline
# ---------------------------------------------------------------------------


class ScanPipeline:
    """Orchestrates the six-step FileGuard scan pipeline with OTel instrumentation.

    All engines are injected at construction time to enable unit testing via
    mocks without touching the real AV daemon, DLP APIs, or database.

    The :meth:`run` method is the primary entry point.  It:
    1. Opens a root OTel span (``fileguard.scan``) that encompasses the full run.
    2. Executes each step via :meth:`_run_step`, which opens a child span per step.
    3. On any step failure: sets ``context.metadata["disposition"] = "block"`` and
       re-raises a :class:`PipelineError`.

    Args:
        extractor: :class:`~fileguard.core.document_extractor.DocumentExtractor`
            instance for text extraction (required).
        pii_detector: :class:`~fileguard.core.pii_detector.PIIDetector` instance
            for PII pattern matching (required).
        av_engine: AV engine adapter.  When ``None`` the ``av_scan`` step is
            skipped (useful for development environments without a ClamAV daemon).
        redaction_engine: Optional object implementing
            :class:`RedactionEngineProtocol`.  When ``None`` the ``redact`` step
            is skipped.
        disposition_engine: Optional object implementing
            :class:`DispositionEngineProtocol`.  When ``None`` a built-in default
            disposition rule is applied (see :meth:`_step_disposition`).
        audit_callable: Optional async callable ``(context) -> None`` invoked
            during the ``audit`` step.  When ``None`` the step is skipped.

    Example — minimal pipeline (no AV, no audit)::

        pipeline = ScanPipeline(
            extractor=DocumentExtractor(max_workers=2),
            pii_detector=PIIDetector(),
        )
        context = ScanContext(file_bytes=b"...", mime_type="text/plain")
        await pipeline.run(context)
        print(context.metadata["disposition"])

    Example — full pipeline::

        from fileguard.core.clamav_adapter import ClamAVAdapter

        pipeline = ScanPipeline(
            extractor=DocumentExtractor(),
            pii_detector=PIIDetector(),
            av_engine=ClamAVAdapter(host="clamav", port=3310),
            audit_callable=my_audit_fn,
        )
    """

    def __init__(
        self,
        *,
        extractor: DocumentExtractor,
        pii_detector: PIIDetector,
        av_engine: AVEngineAdapterProtocol | None = None,
        redaction_engine: RedactionEngineProtocol | None = None,
        disposition_engine: DispositionEngineProtocol | None = None,
        audit_callable: Any | None = None,
    ) -> None:
        self._extractor = extractor
        self._pii_detector = pii_detector
        self._av_engine = av_engine
        self._redaction_engine = redaction_engine
        self._disposition_engine = disposition_engine
        self._audit_callable = audit_callable

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, context: ScanContext) -> ScanContext:
        """Execute the full scan pipeline on *context*.

        Runs the six steps (extract → av_scan → pii_detect → redact →
        disposition → audit) in order.  Each step opens a child OTel span.

        On successful completion, ``context.metadata["disposition"]`` is set to
        one of ``"pass"``, ``"quarantine"``, or ``"block"`` and the method
        returns *context*.

        On failure in any step, ``context.metadata["disposition"]`` is set to
        ``"block"``, ``context.metadata["pipeline_failed"]`` is ``True``, and a
        :class:`PipelineError` is raised.  The caller can inspect *context* even
        after a :class:`PipelineError` to determine which step failed and what
        partial results were produced.

        Args:
            context: The shared scan context to process.  Modified in place.

        Returns:
            The same *context* object (for chaining convenience).

        Raises:
            :class:`PipelineError`: If any pipeline step raises an exception.
                The ``step_name`` attribute identifies the failing step and
                ``original`` carries the underlying exception.
        """
        pipeline_start_ms = int(time.monotonic() * 1000)

        with tracer.start_as_current_span(
            "fileguard.scan",
            kind=trace.SpanKind.INTERNAL,
        ) as root_span:
            root_span.set_attribute("scan.id", context.scan_id)
            if context.tenant_id:
                root_span.set_attribute("scan.tenant_id", context.tenant_id)
            root_span.set_attribute("scan.mime_type", context.mime_type)
            root_span.set_attribute("scan.file_size_bytes", len(context.file_bytes))

            try:
                await self._run_step(context, "extract", self._step_extract)
                await self._run_step(context, "av_scan", self._step_av_scan)
                await self._run_step(context, "pii_detect", self._step_pii_detect)
                await self._run_step(context, "redact", self._step_redact)
                await self._run_step(context, "disposition", self._step_disposition)
                await self._run_step(context, "audit", self._step_audit)

                elapsed_ms = int(time.monotonic() * 1000) - pipeline_start_ms
                context.metadata["scan_duration_ms"] = elapsed_ms

                # Ensure disposition is always set after a successful run.
                if "disposition" not in context.metadata:
                    context.metadata["disposition"] = "pass"

                root_span.set_attribute(
                    "scan.disposition", context.metadata["disposition"]
                )
                root_span.set_attribute("scan.findings_count", len(context.findings))
                root_span.set_attribute("scan.duration_ms", elapsed_ms)

                logger.info(
                    "ScanPipeline complete: scan_id=%s disposition=%s "
                    "findings=%d duration_ms=%d",
                    context.scan_id,
                    context.metadata["disposition"],
                    len(context.findings),
                    elapsed_ms,
                )

            except PipelineError as exc:
                elapsed_ms = int(time.monotonic() * 1000) - pipeline_start_ms
                context.metadata["scan_duration_ms"] = elapsed_ms
                context.metadata["disposition"] = _FAIL_SECURE_DISPOSITION
                context.metadata["pipeline_failed"] = True

                root_span.record_exception(exc.original)
                root_span.set_status(Status(StatusCode.ERROR, str(exc)))
                root_span.set_attribute("scan.disposition", _FAIL_SECURE_DISPOSITION)
                root_span.set_attribute("scan.pipeline_failed", True)
                root_span.set_attribute("scan.failed_step", exc.step_name)
                root_span.set_attribute("scan.duration_ms", elapsed_ms)

                logger.error(
                    "ScanPipeline failed at step '%s': scan_id=%s error=%r",
                    exc.step_name,
                    context.scan_id,
                    exc.original,
                )
                raise

        return context

    # ------------------------------------------------------------------
    # Internal step runner
    # ------------------------------------------------------------------

    async def _run_step(
        self,
        context: ScanContext,
        step_name: str,
        step_fn: Any,
    ) -> None:
        """Execute a single pipeline step inside a named OTel child span.

        Opens a child span named ``fileguard.<step_name>`` under the current
        active span.  Records timing, exceptions, and span status automatically.

        On success: the span is closed normally and the method returns.
        On exception: the exception is recorded on the span, appended to
        ``context.errors``, and re-raised as a :class:`PipelineError`.

        Args:
            context: The shared scan context.
            step_name: Short identifier used for span naming and error messages.
            step_fn: Async callable ``(context) -> None`` for the step.

        Raises:
            :class:`PipelineError`: Wrapping any exception raised by *step_fn*.
        """
        with tracer.start_as_current_span(f"fileguard.{step_name}") as span:
            span.set_attribute("step.name", step_name)
            span.set_attribute("scan.id", context.scan_id)
            step_start_ms = int(time.monotonic() * 1000)

            try:
                await step_fn(context)
                elapsed_ms = int(time.monotonic() * 1000) - step_start_ms
                span.set_attribute("step.duration_ms", elapsed_ms)
                logger.debug(
                    "ScanPipeline step '%s' complete: scan_id=%s duration_ms=%d",
                    step_name,
                    context.scan_id,
                    elapsed_ms,
                )

            except PipelineError:
                # Already wrapped — propagate directly without double-wrapping.
                raise

            except Exception as exc:
                elapsed_ms = int(time.monotonic() * 1000) - step_start_ms
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("step.duration_ms", elapsed_ms)
                span.set_attribute("step.error", type(exc).__name__)

                error_msg = (
                    f"step={step_name} error={type(exc).__name__}: {exc}"
                )
                context.errors.append(error_msg)

                raise PipelineError(step_name, exc) from exc

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _step_extract(self, context: ScanContext) -> None:
        """Step 1 — Extract normalised text from the document.

        Calls :meth:`~fileguard.core.document_extractor.DocumentExtractor.extract`
        and stores the result in ``context.extracted_text`` and
        ``context.byte_offsets``.  The character count is stored in
        ``context.metadata["extracted_chars"]`` for observability.

        Raises:
            :class:`~fileguard.core.document_extractor.ExtractionError`:
                If the MIME type is unsupported or the file is corrupt.
        """
        result = await self._extractor.extract(context.file_bytes, context.mime_type)
        context.extracted_text = result.text
        context.byte_offsets = result.byte_offsets
        context.metadata["extracted_chars"] = len(result.text)

    async def _step_av_scan(self, context: ScanContext) -> None:
        """Step 2 — Scan for malware with the configured AV engine.

        Calls :meth:`scan_bytes` on the injected AV engine adapter.  AV findings
        (``type="av_threat"``) are appended to ``context.findings``.  The AV
        status, engine name, and scan duration are stored in
        ``context.metadata``.

        When ``av_engine`` was not supplied at construction, this step is a no-op.

        Raises:
            :class:`AVScanRejectedError`: If the AV engine returns
                ``status="rejected"``, indicating an engine-level failure (not a
                threat).  Per the fail-secure contract this triggers pipeline
                failure and disposition ``"block"``.
        """
        if self._av_engine is None:
            logger.debug(
                "av_scan step skipped: no AV engine configured (scan_id=%s)",
                context.scan_id,
            )
            return

        result = await self._av_engine.scan_bytes(context.file_bytes)

        # Append all AV findings to the shared findings list.
        findings = list(result.findings)
        context.findings.extend(findings)

        context.metadata["av_status"] = result.status
        context.metadata["av_engine"] = result.engine
        context.metadata["av_duration_ms"] = result.duration_ms

        if result.status == "rejected":
            raise AVScanRejectedError(
                f"AV engine '{result.engine}' rejected the scan (engine failure); "
                "applying fail-secure block disposition"
            )

        if result.status == "flagged":
            context.metadata["av_threats"] = [
                getattr(f, "match", str(f)) for f in findings
            ]
            logger.warning(
                "AV scan flagged %d threat(s): scan_id=%s engine=%s",
                len(findings),
                context.scan_id,
                result.engine,
            )

    async def _step_pii_detect(self, context: ScanContext) -> None:
        """Step 3 — Detect PII patterns in the extracted text.

        Calls :meth:`~fileguard.core.pii_detector.PIIDetector.scan` which
        appends :class:`~fileguard.core.pii_detector.PIIFinding` objects to
        ``context.findings``.  The count of PII findings is stored in
        ``context.metadata["pii_findings_count"]``.

        This step is a no-op (no findings, no error) when
        ``context.extracted_text`` is ``None`` or empty.
        """
        self._pii_detector.scan(context)
        pii_count = sum(
            1 for f in context.findings if getattr(f, "type", None) == "pii"
        )
        context.metadata["pii_findings_count"] = pii_count

    async def _step_redact(self, context: ScanContext) -> None:
        """Step 4 — Redact PII spans from the document.

        Calls ``redaction_engine.redact(context)`` if a redaction engine was
        provided.  When no engine is configured, this step is a no-op.
        """
        if self._redaction_engine is None:
            logger.debug(
                "redact step skipped: no redaction engine configured (scan_id=%s)",
                context.scan_id,
            )
            return

        self._redaction_engine.redact(context)

    async def _step_disposition(self, context: ScanContext) -> None:
        """Step 5 — Determine the disposition action for this file.

        When a ``disposition_engine`` was supplied, delegates to it by calling
        ``disposition_engine.evaluate(context)`` and storing the result in
        ``context.metadata["disposition"]``.

        When no engine is configured, applies built-in default rules:

        * ``"block"``  — if the AV scan was flagged or any AV-threat findings
          are present.
        * ``"pass"``   — for all other outcomes (clean AV, PII-only, or no
          engine results).  Callers that want to quarantine PII-flagged files
          should inject a :class:`DispositionEngineProtocol`.
        """
        if self._disposition_engine is not None:
            disposition = self._disposition_engine.evaluate(context)
            context.metadata["disposition"] = disposition
            return

        # Built-in default disposition logic.
        av_status = context.metadata.get("av_status")
        has_av_threat = any(
            getattr(f, "type", None) == "av_threat" for f in context.findings
        )

        if av_status == "flagged" or has_av_threat:
            context.metadata["disposition"] = "block"
        else:
            context.metadata["disposition"] = "pass"

    async def _step_audit(self, context: ScanContext) -> None:
        """Step 6 — Persist the scan result to the audit log.

        Calls ``await audit_callable(context)`` if one was provided.  When no
        callable is configured, this step is a no-op.

        The audit callable is responsible for constructing the
        :class:`~fileguard.models.scan_event.ScanEvent` record and persisting
        it via :class:`~fileguard.services.audit.AuditService`.
        """
        if self._audit_callable is None:
            logger.debug(
                "audit step skipped: no audit callable configured (scan_id=%s)",
                context.scan_id,
            )
            return

        await self._audit_callable(context)
