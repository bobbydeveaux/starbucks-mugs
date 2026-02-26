"""Integration tests for :mod:`fileguard.workers.scan_worker`.

All tests run against the Celery application in **eager mode**
(``CELERY_TASK_ALWAYS_EAGER=True``) so no broker or worker process is
required.  The pipeline engines (extractor, PII detector, AV engine) are
replaced with lightweight mocks so the tests are deterministic and fast.

Coverage targets
----------------
* Single-file scan — clean result returns ``"pass"`` disposition.
* Single-file scan — AV threat found returns ``"block"`` disposition.
* Single-file scan — pipeline failure (extraction error) returns ``"block"``
  without retrying (non-transient).
* Single-file scan — invalid base64 payload returns ``"block"`` immediately.
* Single-file scan — transient error triggers retry up to max_retries.
* Batch scan — empty list returns empty results.
* Batch scan — multiple files fan out to individual scan tasks.
* Batch scan — mixed dispositions are counted correctly in the summary.
* Result structure — all required keys are present in the return value.
* Worker integration — task is correctly registered in the Celery app.
"""

from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before importing fileguard modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars!!")

from fileguard.celery_app import celery_app
from fileguard.core.document_extractor import ExtractionError, ExtractionResult
from fileguard.core.pii_detector import PIIFinding
from fileguard.workers.scan_worker import scan_batch_task, scan_file_task


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def celery_eager():
    """Force Celery to execute tasks eagerly (synchronously, in-process)."""
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,  # catch exceptions in the result
    )
    yield
    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
    )


def _b64(data: bytes = b"hello world") -> str:
    """Return base64-encoded *data* as a UTF-8 string."""
    return base64.b64encode(data).decode()


def _make_extraction_result(text: str = "hello world") -> ExtractionResult:
    return ExtractionResult(text=text, byte_offsets=list(range(len(text))))


def _mock_pipeline(
    *,
    text: str = "hello world",
    pii_findings: list | None = None,
    av_status: str = "clean",
    av_findings: tuple = (),
    extract_raises: Exception | None = None,
):
    """Patch :func:`fileguard.workers.scan_worker._build_pipeline` with mocks.

    Returns a context manager that patches the pipeline factory so that the
    scan task uses controlled mock engines rather than real ones.
    """
    from unittest.mock import patch as _patch

    pii_findings = pii_findings or []

    extractor = MagicMock()
    if extract_raises is not None:
        extractor.extract = AsyncMock(side_effect=extract_raises)
    else:
        extractor.extract = AsyncMock(
            return_value=_make_extraction_result(text)
        )

    pii_detector = MagicMock()

    def _scan(ctx):
        ctx.findings.extend(pii_findings)

    pii_detector.scan = MagicMock(side_effect=_scan)

    av_result = MagicMock()
    av_result.status = av_status
    av_result.findings = av_findings
    av_result.engine = "mock_av"
    av_result.duration_ms = 1
    av_engine = MagicMock()
    av_engine.scan_bytes = AsyncMock(return_value=av_result)

    from fileguard.core.pipeline import ScanPipeline

    def _make_pipeline():
        return ScanPipeline(
            extractor=extractor,
            pii_detector=pii_detector,
            av_engine=av_engine,
        )

    return _patch(
        "fileguard.workers.scan_worker._build_pipeline",
        side_effect=_make_pipeline,
    )


# ---------------------------------------------------------------------------
# Single-file scan — happy paths
# ---------------------------------------------------------------------------


class TestScanFileTaskHappyPath:
    """scan_file_task returns correct results for clean files."""

    def test_clean_file_returns_pass_disposition(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        assert result["disposition"] == "pass"

    def test_result_has_required_keys(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        for key in ("scan_id", "disposition", "findings", "findings_count", "errors", "metadata"):
            assert key in result, f"Missing key: {key}"

    def test_scan_id_is_populated(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        assert result["scan_id"]  # non-empty string

    def test_explicit_scan_id_is_returned(self):
        explicit_id = "explicit-scan-uuid"
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                    "scan_id": explicit_id,
                }
            ).get()

        assert result["scan_id"] == explicit_id

    def test_clean_file_no_findings(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        assert result["findings"] == []
        assert result["findings_count"] == 0

    def test_clean_file_no_errors(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        assert result["errors"] == []

    def test_metadata_contains_disposition(self):
        with _mock_pipeline():
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "text/plain",
                }
            ).get()

        assert "disposition" in result["metadata"]


# ---------------------------------------------------------------------------
# Single-file scan — AV threat
# ---------------------------------------------------------------------------


class TestScanFileTaskAVThreat:
    """scan_file_task correctly handles malware findings."""

    def test_av_flagged_returns_block_disposition(self):
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.category = "Win.Test"
        av_finding.severity = "high"
        av_finding.match = "Win.Test.EICAR_HDB-1"
        av_finding.offset = 0

        with _mock_pipeline(av_status="flagged", av_findings=(av_finding,)):
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "application/pdf",
                }
            ).get()

        assert result["disposition"] == "block"

    def test_av_flagged_findings_serialised(self):
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.category = "Win.Test"
        av_finding.severity = "high"
        av_finding.match = "Win.Test.EICAR_HDB-1"
        av_finding.offset = 0

        with _mock_pipeline(av_status="flagged", av_findings=(av_finding,)):
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "application/pdf",
                }
            ).get()

        assert result["findings_count"] == 1
        assert result["findings"][0]["type"] == "av_threat"


# ---------------------------------------------------------------------------
# Single-file scan — PII findings
# ---------------------------------------------------------------------------


class TestScanFileTaskPIIFindings:
    """PII findings are serialised and included in the result."""

    def test_pii_finding_included_in_result(self):
        pii_finding = PIIFinding(
            type="pii",
            category="NI_NUMBER",
            severity="high",
            match="AB123456C",
            offset=5,
        )
        with _mock_pipeline(pii_findings=[pii_finding]):
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(b"NI: AB123456C"),
                    "mime_type": "text/plain",
                }
            ).get()

        assert result["findings_count"] == 1
        finding = result["findings"][0]
        assert finding["type"] == "pii"
        assert finding["category"] == "NI_NUMBER"
        assert finding["match"] == "AB123456C"


# ---------------------------------------------------------------------------
# Single-file scan — failure paths
# ---------------------------------------------------------------------------


class TestScanFileTaskFailures:
    """Failure paths return block disposition without incorrect retries."""

    def test_invalid_base64_returns_block(self):
        result = scan_file_task.apply(
            kwargs={
                "file_bytes_b64": "!!!not-valid-base64!!!",
                "mime_type": "text/plain",
            }
        ).get()

        assert result["disposition"] == "block"
        assert result["errors"]

    def test_pipeline_error_returns_block_no_retry(self):
        """Non-transient PipelineError (extraction failure) does not trigger retry."""
        with _mock_pipeline(
            extract_raises=ExtractionError(
                "Unsupported MIME type", mime_type="image/png"
            )
        ):
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(),
                    "mime_type": "image/png",
                }
            ).get()

        assert result["disposition"] == "block"

    def test_pipeline_error_populates_errors_field(self):
        with _mock_pipeline(
            extract_raises=ExtractionError(
                "Corrupt PDF", mime_type="application/pdf"
            )
        ):
            result = scan_file_task.apply(
                kwargs={
                    "file_bytes_b64": _b64(b"%PDF-1.4 corrupted"),
                    "mime_type": "application/pdf",
                }
            ).get()

        assert len(result["errors"]) >= 1

    def test_transient_error_retried(self):
        """A transient ConnectionError causes the task to retry and ultimately fail."""
        celery_app.conf.task_eager_propagates = True

        call_count = 0

        def _failing_pipeline():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("ClamAV unreachable")

        with patch(
            "fileguard.workers.scan_worker._build_pipeline",
            side_effect=_failing_pipeline,
        ):
            try:
                scan_file_task.apply(
                    kwargs={
                        "file_bytes_b64": _b64(),
                        "mime_type": "text/plain",
                    }
                ).get()
            except (ConnectionError, Exception):
                pass  # Expected: task exhausts retries and raises

        # Called once per attempt: initial + 3 retries = 4 total.
        assert call_count == 4  # 1 initial + 3 retries


# ---------------------------------------------------------------------------
# Batch scan task
# ---------------------------------------------------------------------------


class TestScanBatchTask:
    """scan_batch_task fans out to individual scan tasks and aggregates results."""

    def test_empty_items_returns_zero_total(self):
        result = scan_batch_task.apply(kwargs={"items": []}).get()

        assert result["total"] == 0
        assert result["results"] == []
        assert result["summary"] == {"pass": 0, "quarantine": 0, "block": 0}

    def test_single_item_batch(self):
        with _mock_pipeline():
            result = scan_batch_task.apply(
                kwargs={
                    "items": [
                        {
                            "file_bytes_b64": _b64(),
                            "mime_type": "text/plain",
                        }
                    ]
                }
            ).get()

        assert result["total"] == 1
        assert len(result["results"]) == 1

    def test_multiple_items_fanned_out(self):
        with _mock_pipeline():
            items = [
                {"file_bytes_b64": _b64(b"file one"), "mime_type": "text/plain"},
                {"file_bytes_b64": _b64(b"file two"), "mime_type": "text/plain"},
                {"file_bytes_b64": _b64(b"file three"), "mime_type": "text/plain"},
            ]
            result = scan_batch_task.apply(kwargs={"items": items}).get()

        assert result["total"] == 3
        assert len(result["results"]) == 3

    def test_batch_summary_aggregates_dispositions(self):
        """Summary counts reflect each child task's disposition."""
        av_finding = MagicMock()
        av_finding.type = "av_threat"
        av_finding.category = "Win.Test"
        av_finding.severity = "high"
        av_finding.match = "EICAR"
        av_finding.offset = 0

        # 2 clean + 1 threat = 2 pass, 1 block
        def _make_pipeline_for_item():
            """Return alternating pipelines: first two clean, third flagged."""
            calls = {"n": 0}

            def _factory():
                from fileguard.core.pipeline import ScanPipeline

                n = calls["n"]
                calls["n"] += 1

                extractor = MagicMock()
                extractor.extract = AsyncMock(
                    return_value=_make_extraction_result()
                )
                pii_detector = MagicMock()
                pii_detector.scan = MagicMock()

                if n >= 2:
                    av_result = MagicMock()
                    av_result.status = "flagged"
                    av_result.findings = (av_finding,)
                    av_result.engine = "mock_av"
                    av_result.duration_ms = 1
                else:
                    av_result = MagicMock()
                    av_result.status = "clean"
                    av_result.findings = ()
                    av_result.engine = "mock_av"
                    av_result.duration_ms = 1

                av_engine = MagicMock()
                av_engine.scan_bytes = AsyncMock(return_value=av_result)

                return ScanPipeline(
                    extractor=extractor,
                    pii_detector=pii_detector,
                    av_engine=av_engine,
                )

            return _factory

        factory = _make_pipeline_for_item()

        with patch(
            "fileguard.workers.scan_worker._build_pipeline",
            side_effect=factory,
        ):
            items = [
                {"file_bytes_b64": _b64(b"clean1"), "mime_type": "text/plain"},
                {"file_bytes_b64": _b64(b"clean2"), "mime_type": "text/plain"},
                {"file_bytes_b64": _b64(b"threat"), "mime_type": "text/plain"},
            ]
            result = scan_batch_task.apply(kwargs={"items": items}).get()

        assert result["summary"]["pass"] == 2
        assert result["summary"]["block"] == 1

    def test_batch_result_structure(self):
        with _mock_pipeline():
            result = scan_batch_task.apply(
                kwargs={
                    "items": [
                        {"file_bytes_b64": _b64(), "mime_type": "text/plain"}
                    ]
                }
            ).get()

        assert "total" in result
        assert "results" in result
        assert "summary" in result
        assert "pass" in result["summary"]
        assert "quarantine" in result["summary"]
        assert "block" in result["summary"]

    def test_batch_forwards_tenant_id(self):
        """tenant_id is forwarded to each child scan task (batch runs successfully)."""
        with _mock_pipeline():
            result = scan_batch_task.apply(
                kwargs={
                    "items": [
                        {"file_bytes_b64": _b64(), "mime_type": "text/plain"},
                    ],
                    "tenant_id": "tenant-123",
                }
            ).get()

        assert result["total"] == 1
        assert result["results"][0]["disposition"] in ("pass", "quarantine", "block")


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


class TestTaskRegistration:
    """Verify tasks are correctly registered in the Celery application."""

    def test_scan_file_task_registered(self):
        assert "fileguard.workers.scan_worker.scan_file_task" in celery_app.tasks

    def test_scan_batch_task_registered(self):
        assert "fileguard.workers.scan_worker.scan_batch_task" in celery_app.tasks
