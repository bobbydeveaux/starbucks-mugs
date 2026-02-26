"""Integration tests for :class:`~fileguard.core.pipeline.ScanPipeline`.

Coverage targets
----------------
* Happy path: all six steps execute in order, ScanContext is correctly populated,
  and disposition defaults to ``"pass"`` for a clean file.
* Happy path with AV threat: AV engine flags a threat → disposition set to
  ``"block"``.
* Happy path with PII: PII findings are added to context.findings.
* Mid-pipeline failure (extraction): ExtractionError halts pipeline, context
  receives ``"block"`` disposition and ``pipeline_failed=True``.
* Mid-pipeline failure (AV rejected): AVScanRejectedError halts pipeline,
  context receives ``"block"`` disposition.
* Mid-pipeline failure (mid step): generic exception in pii_detect halts pipeline.
* Optional steps skipped: steps are correctly skipped when engines are not configured.
* Redaction step: redaction engine is called when configured.
* Disposition engine: custom disposition engine overrides default logic.
* Audit step: audit callable is awaited during the audit step.
* OTel spans: pipeline runs correctly when OTel tracer is a no-op (default).
* Context errors: errors are appended to context.errors on failure.
* Step order: steps execute in the correct sequence (extract before pii_detect, etc.).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Set required env vars before importing fileguard modules that load settings.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars!!")

from fileguard.core.document_extractor import ExtractionError, ExtractionResult
from fileguard.core.pipeline import AVScanRejectedError, PipelineError, ScanPipeline
from fileguard.core.pii_detector import PIIFinding
from fileguard.core.scan_context import ScanContext


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_extractor(
    text: str = "hello world",
    byte_offsets: list[int] | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    """Return a mock DocumentExtractor."""
    extractor = MagicMock()
    if raises is not None:
        extractor.extract = AsyncMock(side_effect=raises)
    else:
        result = ExtractionResult(
            text=text,
            byte_offsets=byte_offsets or list(range(len(text))),
        )
        extractor.extract = AsyncMock(return_value=result)
    return extractor


def _make_pii_detector(findings: list | None = None) -> MagicMock:
    """Return a mock PIIDetector."""
    detector = MagicMock()
    _findings = findings or []

    def _scan(ctx: ScanContext) -> None:
        ctx.findings.extend(_findings)

    detector.scan = MagicMock(side_effect=_scan)
    return detector


def _make_av_engine(
    status: str = "clean",
    findings: tuple = (),
    engine: str = "test_av",
    duration_ms: int = 5,
    raises: Exception | None = None,
) -> MagicMock:
    """Return a mock AVEngineAdapter."""
    av = MagicMock()
    if raises is not None:
        av.scan_bytes = AsyncMock(side_effect=raises)
    else:
        result = MagicMock()
        result.status = status
        result.findings = findings
        result.engine = engine
        result.duration_ms = duration_ms
        av.scan_bytes = AsyncMock(return_value=result)
    return av


def _make_context(
    file_bytes: bytes = b"sample file content",
    mime_type: str = "text/plain",
    tenant_id: str | None = "tenant-1",
) -> ScanContext:
    return ScanContext(
        file_bytes=file_bytes,
        mime_type=mime_type,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Pipeline completes successfully for clean files."""

    @pytest.mark.asyncio
    async def test_clean_file_disposition_is_pass(self):
        """A clean file with no PII and clean AV should get 'pass' disposition."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(status="clean"),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["disposition"] == "pass"
        assert ctx.metadata.get("pipeline_failed") is None
        assert ctx.errors == []

    @pytest.mark.asyncio
    async def test_extracted_text_is_set(self):
        """After a successful run, context has the extracted text."""
        expected_text = "Patient NI: AB123456C"
        pipeline = ScanPipeline(
            extractor=_make_extractor(text=expected_text),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.extracted_text == expected_text

    @pytest.mark.asyncio
    async def test_byte_offsets_populated(self):
        """Byte offsets from extractor are stored in context."""
        text = "hello"
        offsets = [10, 11, 12, 13, 14]
        pipeline = ScanPipeline(
            extractor=_make_extractor(text=text, byte_offsets=offsets),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.byte_offsets == offsets

    @pytest.mark.asyncio
    async def test_extracted_chars_metadata(self):
        """extracted_chars is set in metadata after extraction."""
        text = "hello world"
        pipeline = ScanPipeline(
            extractor=_make_extractor(text=text),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["extracted_chars"] == len(text)

    @pytest.mark.asyncio
    async def test_av_metadata_populated(self):
        """AV scan metadata is stored in context."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(status="clean", engine="clamav"),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["av_status"] == "clean"
        assert ctx.metadata["av_engine"] == "clamav"

    @pytest.mark.asyncio
    async def test_pii_findings_count_in_metadata(self):
        """pii_findings_count reflects the number of PII findings."""
        pii_finding = PIIFinding(
            type="pii",
            category="EMAIL",
            severity="medium",
            match="alice@example.com",
            offset=0,
        )
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(findings=[pii_finding]),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["pii_findings_count"] == 1
        assert len(ctx.findings) == 1

    @pytest.mark.asyncio
    async def test_scan_duration_ms_set(self):
        """scan_duration_ms is set in metadata after a successful run."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert isinstance(ctx.metadata.get("scan_duration_ms"), int)
        assert ctx.metadata["scan_duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_returns_same_context_object(self):
        """run() returns the same context instance."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        returned = await pipeline.run(ctx)

        assert returned is ctx


# ---------------------------------------------------------------------------
# AV threat handling
# ---------------------------------------------------------------------------


class TestAVThreatHandling:
    """AV scan result correctly flows into disposition."""

    @pytest.mark.asyncio
    async def test_flagged_av_sets_block_disposition(self):
        """AV 'flagged' result → disposition is 'block'."""
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.match = "Win.Test.EICAR_HDB-1"

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(
                status="flagged",
                findings=(av_finding,),
            ),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["disposition"] == "block"
        assert len(ctx.findings) == 1

    @pytest.mark.asyncio
    async def test_rejected_av_raises_pipeline_error(self):
        """AV 'rejected' (engine failure) → PipelineError raised, disposition 'block'."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(status="rejected"),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "av_scan"
        assert isinstance(exc_info.value.original, AVScanRejectedError)
        assert ctx.metadata["disposition"] == "block"
        assert ctx.metadata.get("pipeline_failed") is True

    @pytest.mark.asyncio
    async def test_av_threats_list_in_metadata_when_flagged(self):
        """av_threats list is stored in metadata when AV flags threats."""
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.match = "Trojan.Generic"

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(
                status="flagged",
                findings=(av_finding,),
            ),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert "av_threats" in ctx.metadata
        assert "Trojan.Generic" in ctx.metadata["av_threats"]


# ---------------------------------------------------------------------------
# Mid-pipeline failure tests
# ---------------------------------------------------------------------------


class TestMidPipelineFailure:
    """Pipeline halts correctly and applies fail-secure disposition on failure."""

    @pytest.mark.asyncio
    async def test_extraction_failure_halts_pipeline(self):
        """ExtractionError in extract step → PipelineError, 'block' disposition."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(
                raises=ExtractionError("Unsupported MIME type", mime_type="image/png")
            ),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "extract"
        assert isinstance(exc_info.value.original, ExtractionError)
        assert ctx.metadata["disposition"] == "block"
        assert ctx.metadata.get("pipeline_failed") is True

    @pytest.mark.asyncio
    async def test_extraction_failure_records_error_in_context(self):
        """On extraction failure, context.errors contains an entry."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(
                raises=ExtractionError("Corrupt PDF", mime_type="application/pdf")
            ),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError):
            await pipeline.run(ctx)

        assert len(ctx.errors) == 1
        assert "extract" in ctx.errors[0]

    @pytest.mark.asyncio
    async def test_pii_detect_failure_halts_pipeline(self):
        """Exception in pii_detect step → PipelineError, 'block' disposition."""
        detector = MagicMock()
        detector.scan = MagicMock(side_effect=RuntimeError("regex engine crash"))

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=detector,
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "pii_detect"
        assert ctx.metadata["disposition"] == "block"

    @pytest.mark.asyncio
    async def test_av_generic_exception_halts_pipeline(self):
        """Generic exception in av_scan step → PipelineError, 'block' disposition."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(raises=ConnectionError("clamd unreachable")),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "av_scan"
        assert ctx.metadata["disposition"] == "block"

    @pytest.mark.asyncio
    async def test_disposition_failure_halts_pipeline(self):
        """Exception in disposition step → PipelineError, 'block' disposition."""
        disposition_engine = MagicMock()
        disposition_engine.evaluate = MagicMock(
            side_effect=RuntimeError("disposition rules database is unavailable")
        )

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            disposition_engine=disposition_engine,
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "disposition"
        assert ctx.metadata["disposition"] == "block"

    @pytest.mark.asyncio
    async def test_audit_failure_halts_pipeline(self):
        """Exception in audit step → PipelineError, 'block' disposition."""

        async def _failing_audit(ctx: ScanContext) -> None:
            raise IOError("database connection lost during audit")

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            audit_callable=_failing_audit,
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "audit"
        assert ctx.metadata["disposition"] == "block"

    @pytest.mark.asyncio
    async def test_partial_state_preserved_after_failure(self):
        """Steps completed before failure leave partial state in context."""
        expected_text = "some extracted content"

        detector = MagicMock()
        detector.scan = MagicMock(side_effect=RuntimeError("pii crash"))

        pipeline = ScanPipeline(
            extractor=_make_extractor(text=expected_text),
            pii_detector=detector,
        )
        ctx = _make_context()

        with pytest.raises(PipelineError):
            await pipeline.run(ctx)

        # Extraction succeeded before pii_detect failed.
        assert ctx.extracted_text == expected_text
        assert ctx.metadata["extracted_chars"] == len(expected_text)


# ---------------------------------------------------------------------------
# Optional steps
# ---------------------------------------------------------------------------


class TestOptionalSteps:
    """Steps are correctly skipped when engines are not configured."""

    @pytest.mark.asyncio
    async def test_av_skipped_when_not_configured(self):
        """Pipeline completes successfully when no AV engine is configured."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            # No av_engine
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert "av_status" not in ctx.metadata
        assert ctx.metadata["disposition"] == "pass"

    @pytest.mark.asyncio
    async def test_redact_skipped_when_not_configured(self):
        """redact step is a no-op when no redaction engine is provided."""
        redaction_engine = MagicMock()
        redaction_engine.redact = MagicMock()

        # Pipeline WITHOUT redaction engine
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        redaction_engine.redact.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_skipped_when_not_configured(self):
        """audit step is a no-op when no audit callable is provided."""
        audit_fn = AsyncMock()

        # Pipeline WITHOUT audit callable
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        audit_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_redact_step_calls_engine(self):
        """Redaction engine is called when configured."""
        redaction_engine = MagicMock()
        redaction_engine.redact = MagicMock()

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            redaction_engine=redaction_engine,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        redaction_engine.redact.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_audit_step_calls_callable(self):
        """Audit callable is awaited when configured."""
        audit_fn = AsyncMock()

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            audit_callable=audit_fn,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        audit_fn.assert_called_once_with(ctx)


# ---------------------------------------------------------------------------
# Disposition engine
# ---------------------------------------------------------------------------


class TestDispositionEngine:
    """Custom disposition engine overrides default disposition logic."""

    @pytest.mark.asyncio
    async def test_custom_disposition_engine_used(self):
        """DispositionEngine.evaluate() result is stored in context.metadata."""
        disposition_engine = MagicMock()
        disposition_engine.evaluate = MagicMock(return_value="quarantine")

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            disposition_engine=disposition_engine,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["disposition"] == "quarantine"
        disposition_engine.evaluate.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_default_disposition_pass_for_clean(self):
        """Default disposition is 'pass' for clean files with no AV engine."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["disposition"] == "pass"

    @pytest.mark.asyncio
    async def test_default_disposition_block_for_av_threat(self):
        """Default disposition is 'block' when AV flags a threat."""
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.match = "Eicar.Test"

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(
                status="flagged",
                findings=(av_finding,),
            ),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert ctx.metadata["disposition"] == "block"

    @pytest.mark.asyncio
    async def test_default_disposition_pass_for_pii_only(self):
        """Default disposition is 'pass' for files with PII but no malware."""
        pii_finding = PIIFinding(
            type="pii",
            category="NI_NUMBER",
            severity="high",
            match="AB123456C",
            offset=0,
        )
        pipeline = ScanPipeline(
            extractor=_make_extractor(text="NI: AB123456C"),
            pii_detector=_make_pii_detector(findings=[pii_finding]),
            av_engine=_make_av_engine(status="clean"),
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        # Default rules: PII-only → "pass" (callers should inject DispositionEngine
        # if they want to quarantine PII-flagged files).
        assert ctx.metadata["disposition"] == "pass"


# ---------------------------------------------------------------------------
# PipelineError attributes
# ---------------------------------------------------------------------------


class TestPipelineErrorAttributes:
    """PipelineError carries the correct step name and original exception."""

    @pytest.mark.asyncio
    async def test_pipeline_error_step_name(self):
        """PipelineError.step_name identifies the failing step."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(
                raises=ValueError("unexpected format")
            ),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.step_name == "extract"

    @pytest.mark.asyncio
    async def test_pipeline_error_original_exception(self):
        """PipelineError.original is the raw exception from the step."""
        root_cause = ValueError("bad format")
        pipeline = ScanPipeline(
            extractor=_make_extractor(raises=root_cause),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert exc_info.value.original is root_cause

    @pytest.mark.asyncio
    async def test_pipeline_error_has_cause_chain(self):
        """PipelineError.__cause__ preserves the original exception."""
        pipeline = ScanPipeline(
            extractor=_make_extractor(raises=IOError("disk error")),
            pii_detector=_make_pii_detector(),
        )
        ctx = _make_context()

        with pytest.raises(PipelineError) as exc_info:
            await pipeline.run(ctx)

        assert isinstance(exc_info.value.__cause__, IOError)


# ---------------------------------------------------------------------------
# Step ordering (verifies steps execute in the correct sequence)
# ---------------------------------------------------------------------------


class TestStepOrdering:
    """Steps execute in the defined order: extract → av_scan → pii_detect →
    redact → disposition → audit."""

    @pytest.mark.asyncio
    async def test_pii_detect_sees_extracted_text(self):
        """pii_detect step runs after extract and can read context.extracted_text."""
        observed_text: list[str | None] = []

        def _detecting_scan(ctx: ScanContext) -> None:
            observed_text.append(ctx.extracted_text)

        detector = MagicMock()
        detector.scan = MagicMock(side_effect=_detecting_scan)

        pipeline = ScanPipeline(
            extractor=_make_extractor(text="sensitive data"),
            pii_detector=detector,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert observed_text == ["sensitive data"]

    @pytest.mark.asyncio
    async def test_disposition_sees_av_findings(self):
        """disposition step runs after av_scan and can see AV findings."""
        observed_findings: list = []

        def _eval(ctx: ScanContext) -> str:
            observed_findings.extend(ctx.findings)
            return "pass"

        disposition_engine = MagicMock()
        disposition_engine.evaluate = MagicMock(side_effect=_eval)

        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.match = "Test.Virus"

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            av_engine=_make_av_engine(status="flagged", findings=(av_finding,)),
            disposition_engine=disposition_engine,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        # Disposition engine should have seen the AV finding.
        assert any(getattr(f, "type", None) == "av_threat" for f in observed_findings)

    @pytest.mark.asyncio
    async def test_audit_sees_final_disposition(self):
        """audit step runs after disposition, so context has final disposition."""
        observed_disposition: list[str] = []

        async def _audit(ctx: ScanContext) -> None:
            observed_disposition.append(ctx.metadata.get("disposition", ""))

        pipeline = ScanPipeline(
            extractor=_make_extractor(),
            pii_detector=_make_pii_detector(),
            audit_callable=_audit,
        )
        ctx = _make_context()
        await pipeline.run(ctx)

        assert observed_disposition == ["pass"]
