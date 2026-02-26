"""Unit tests for fileguard/schemas/report.py and fileguard/services/reports.py.

All tests are fully offline — database access and file I/O are replaced by
``unittest.mock`` patches so no external services or the filesystem are
required.

Coverage targets:
* VerdictBreakdown validates non-negative counts and exposes a ``total`` property.
* ReportPayload validates period_end > period_start and all required fields.
* ComplianceReportCreate validates period and format constraints.
* ComplianceReportRead is constructable from ORM attributes.
* ReportService.aggregate_metrics queries the correct tables and returns the
  expected ReportPayload.
* ReportService.generate_json_report produces valid, parseable JSON containing
  all top-level keys.
* ReportService.generate_pdf_report produces non-empty bytes beginning with
  the PDF magic header ``%PDF``.
* ReportService.store_report writes the file to the configured directory and
  returns a ``file://`` URI.
* ReportService.create_report_record calls session.add and session.flush.
* ReportService.generate_and_store orchestrates all steps end-to-end.
* generate_compliance_report Celery task delegates to ReportService.
* generate_scheduled_reports Celery task dispatches per-tenant subtasks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from fileguard.schemas.report import (
    ComplianceReportCreate,
    ComplianceReportRead,
    ReportPayload,
    VerdictBreakdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_PERIOD_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PERIOD_END = datetime(2026, 2, 1, tzinfo=timezone.utc)
_GENERATED_AT = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_payload(**overrides: Any) -> ReportPayload:
    defaults = dict(
        tenant_id=_TENANT_ID,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        generated_at=_GENERATED_AT,
        file_count=100,
        verdict_breakdown=VerdictBreakdown(clean=90, flagged=7, rejected=3),
        pii_hits_by_category={"NI_NUMBER": 5, "EMAIL": 12},
        top_file_types={"application/pdf": 40, "text/plain": 60},
        average_scan_duration_ms=42.5,
    )
    defaults.update(overrides)
    return ReportPayload(**defaults)


def _make_report_record(**overrides: Any) -> MagicMock:
    """Return a mock ComplianceReport ORM row."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.tenant_id = _TENANT_ID
    record.period_start = _PERIOD_START
    record.period_end = _PERIOD_END
    record.format = "json"
    record.file_uri = "file:///tmp/fileguard/reports/test.json"
    record.generated_at = _GENERATED_AT
    for k, v in overrides.items():
        setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# VerdictBreakdown
# ---------------------------------------------------------------------------


class TestVerdictBreakdown:
    def test_defaults_are_zero(self) -> None:
        v = VerdictBreakdown()
        assert v.clean == 0
        assert v.flagged == 0
        assert v.rejected == 0

    def test_total_property(self) -> None:
        v = VerdictBreakdown(clean=5, flagged=3, rejected=2)
        assert v.total == 10

    def test_total_with_defaults(self) -> None:
        v = VerdictBreakdown(clean=7)
        assert v.total == 7

    def test_rejects_negative_clean(self) -> None:
        with pytest.raises(Exception):
            VerdictBreakdown(clean=-1)

    def test_rejects_negative_flagged(self) -> None:
        with pytest.raises(Exception):
            VerdictBreakdown(flagged=-1)

    def test_rejects_negative_rejected(self) -> None:
        with pytest.raises(Exception):
            VerdictBreakdown(rejected=-1)


# ---------------------------------------------------------------------------
# ReportPayload
# ---------------------------------------------------------------------------


class TestReportPayload:
    def test_valid_payload_constructed(self) -> None:
        payload = _make_payload()
        assert payload.file_count == 100
        assert payload.verdict_breakdown.clean == 90
        assert payload.pii_hits_by_category["EMAIL"] == 12

    def test_period_end_must_be_after_period_start(self) -> None:
        with pytest.raises(Exception):
            _make_payload(period_end=_PERIOD_START)

    def test_period_end_equal_to_start_rejected(self) -> None:
        with pytest.raises(Exception):
            _make_payload(period_end=_PERIOD_START, period_start=_PERIOD_START)

    def test_file_count_cannot_be_negative(self) -> None:
        with pytest.raises(Exception):
            _make_payload(file_count=-1)

    def test_average_scan_duration_cannot_be_negative(self) -> None:
        with pytest.raises(Exception):
            _make_payload(average_scan_duration_ms=-1.0)

    def test_empty_pii_hits_allowed(self) -> None:
        payload = _make_payload(pii_hits_by_category={})
        assert payload.pii_hits_by_category == {}

    def test_empty_top_file_types_allowed(self) -> None:
        payload = _make_payload(top_file_types={})
        assert payload.top_file_types == {}

    def test_model_dump_json_mode_serialises_uuid(self) -> None:
        payload = _make_payload()
        data = payload.model_dump(mode="json")
        assert isinstance(data["tenant_id"], str)


# ---------------------------------------------------------------------------
# ComplianceReportCreate
# ---------------------------------------------------------------------------


class TestComplianceReportCreate:
    def test_valid_json_format(self) -> None:
        req = ComplianceReportCreate(
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            format="json",
        )
        assert req.format == "json"

    def test_valid_pdf_format(self) -> None:
        req = ComplianceReportCreate(
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            format="pdf",
        )
        assert req.format == "pdf"

    def test_invalid_format_rejected(self) -> None:
        with pytest.raises(Exception):
            ComplianceReportCreate(
                tenant_id=_TENANT_ID,
                period_start=_PERIOD_START,
                period_end=_PERIOD_END,
                format="xml",
            )

    def test_period_end_before_start_rejected(self) -> None:
        with pytest.raises(Exception):
            ComplianceReportCreate(
                tenant_id=_TENANT_ID,
                period_start=_PERIOD_END,
                period_end=_PERIOD_START,
            )

    def test_default_format_is_json(self) -> None:
        req = ComplianceReportCreate(
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
        )
        assert req.format == "json"


# ---------------------------------------------------------------------------
# ComplianceReportRead
# ---------------------------------------------------------------------------


class TestComplianceReportRead:
    def test_from_attributes(self) -> None:
        record = _make_report_record()
        read = ComplianceReportRead.model_validate(record)
        assert read.id == record.id
        assert read.tenant_id == record.tenant_id
        assert read.format == "json"
        assert read.file_uri == record.file_uri

    def test_pdf_format(self) -> None:
        record = _make_report_record(format="pdf")
        read = ComplianceReportRead.model_validate(record)
        assert read.format == "pdf"


# ---------------------------------------------------------------------------
# ReportService.generate_json_report
# ---------------------------------------------------------------------------


class TestGenerateJsonReport:
    def test_returns_bytes(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        result = svc.generate_json_report(payload)
        assert isinstance(result, bytes)

    def test_valid_json(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        data = json.loads(svc.generate_json_report(payload))
        assert isinstance(data, dict)

    def test_contains_file_count(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload(file_count=77)
        data = json.loads(svc.generate_json_report(payload))
        assert data["file_count"] == 77

    def test_contains_verdict_breakdown(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        data = json.loads(svc.generate_json_report(payload))
        assert "verdict_breakdown" in data
        assert data["verdict_breakdown"]["clean"] == 90

    def test_contains_pii_hits_by_category(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        data = json.loads(svc.generate_json_report(payload))
        assert "pii_hits_by_category" in data
        assert data["pii_hits_by_category"]["EMAIL"] == 12

    def test_contains_tenant_id(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        data = json.loads(svc.generate_json_report(payload))
        assert data["tenant_id"] == str(_TENANT_ID)

    def test_contains_period_fields(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        data = json.loads(svc.generate_json_report(payload))
        assert "period_start" in data
        assert "period_end" in data

    def test_zero_file_count(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload(
            file_count=0,
            verdict_breakdown=VerdictBreakdown(),
            pii_hits_by_category={},
        )
        data = json.loads(svc.generate_json_report(payload))
        assert data["file_count"] == 0


# ---------------------------------------------------------------------------
# ReportService.generate_pdf_report
# ---------------------------------------------------------------------------


class TestGeneratePdfReport:
    def test_returns_non_empty_bytes(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        result = svc.generate_pdf_report(payload)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_starts_with_pdf_magic_header(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        result = svc.generate_pdf_report(payload)
        assert result[:4] == b"%PDF"

    def test_pdf_with_empty_pii_hits(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload(pii_hits_by_category={})
        result = svc.generate_pdf_report(payload)
        assert result[:4] == b"%PDF"

    def test_pdf_with_empty_file_types(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload(top_file_types={})
        result = svc.generate_pdf_report(payload)
        assert result[:4] == b"%PDF"

    def test_pdf_with_zero_scans(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload(
            file_count=0,
            verdict_breakdown=VerdictBreakdown(),
            pii_hits_by_category={},
            top_file_types={},
        )
        result = svc.generate_pdf_report(payload)
        assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# ReportService.store_report
# ---------------------------------------------------------------------------


class TestStoreReport:
    def test_writes_file_and_returns_file_uri(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        content = b'{"test": true}'
        with patch("fileguard.services.reports.settings") as mock_settings:
            mock_settings.REPORTS_DIR = str(tmp_path)
            uri = svc.store_report(
                content, "json", _TENANT_ID, _PERIOD_START, _PERIOD_END
            )

        assert uri.startswith("file://")
        # The file should exist on disk
        file_path = uri[len("file://"):]
        with open(file_path, "rb") as fh:
            assert fh.read() == content

    def test_creates_reports_dir_if_missing(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        new_dir = tmp_path / "reports" / "sub"
        with patch("fileguard.services.reports.settings") as mock_settings:
            mock_settings.REPORTS_DIR = str(new_dir)
            uri = svc.store_report(b"data", "json", _TENANT_ID, _PERIOD_START, _PERIOD_END)

        assert new_dir.exists()

    def test_json_extension_for_json_format(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        with patch("fileguard.services.reports.settings") as mock_settings:
            mock_settings.REPORTS_DIR = str(tmp_path)
            uri = svc.store_report(b"{}", "json", _TENANT_ID, _PERIOD_START, _PERIOD_END)

        assert uri.endswith(".json")

    def test_pdf_extension_for_pdf_format(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        with patch("fileguard.services.reports.settings") as mock_settings:
            mock_settings.REPORTS_DIR = str(tmp_path)
            uri = svc.store_report(b"%PDF", "pdf", _TENANT_ID, _PERIOD_START, _PERIOD_END)

        assert uri.endswith(".pdf")

    def test_filename_contains_tenant_id(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        with patch("fileguard.services.reports.settings") as mock_settings:
            mock_settings.REPORTS_DIR = str(tmp_path)
            uri = svc.store_report(b"{}", "json", _TENANT_ID, _PERIOD_START, _PERIOD_END)

        assert str(_TENANT_ID) in uri


# ---------------------------------------------------------------------------
# ReportService.create_report_record
# ---------------------------------------------------------------------------


class TestCreateReportRecord:
    @pytest.mark.asyncio
    async def test_calls_session_add_and_flush(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock(return_value=None)

        await svc.create_report_record(
            session,
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            fmt="json",
            file_uri="file:///tmp/test.json",
            generated_at=_GENERATED_AT,
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_compliance_report_instance(self) -> None:
        from fileguard.models.compliance_report import ComplianceReport
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock(return_value=None)

        result = await svc.create_report_record(
            session,
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            fmt="json",
            file_uri="file:///tmp/test.json",
            generated_at=_GENERATED_AT,
        )

        assert isinstance(result, ComplianceReport)

    @pytest.mark.asyncio
    async def test_report_fields_match_inputs(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock(return_value=None)

        result = await svc.create_report_record(
            session,
            tenant_id=_TENANT_ID,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            fmt="pdf",
            file_uri="file:///tmp/test.pdf",
            generated_at=_GENERATED_AT,
        )

        assert result.tenant_id == _TENANT_ID
        assert result.period_start == _PERIOD_START
        assert result.period_end == _PERIOD_END
        assert result.format == "pdf"
        assert result.file_uri == "file:///tmp/test.pdf"
        assert result.generated_at == _GENERATED_AT


# ---------------------------------------------------------------------------
# ReportService.aggregate_metrics
# ---------------------------------------------------------------------------


def _make_async_session_mock(
    total_count: int = 10,
    verdict_rows: list[tuple[str, int]] | None = None,
    avg_duration: float = 50.0,
    mime_rows: list[tuple[str, int]] | None = None,
    findings_rows: list[tuple[list[dict[str, Any]]]] | None = None,
) -> AsyncMock:
    """Return a mock AsyncSession that returns pre-canned query results."""
    if verdict_rows is None:
        verdict_rows = [("clean", 8), ("flagged", 1), ("rejected", 1)]
    if mime_rows is None:
        mime_rows = [("application/pdf", 7), ("text/plain", 3)]
    if findings_rows is None:
        findings_rows = [
            ([{"category": "EMAIL", "severity": "medium"}],),
            ([{"category": "NI_NUMBER", "severity": "high"}],),
        ]

    session = AsyncMock()

    # We need to return different results depending on which query is executed.
    # We achieve this by tracking call count.
    call_count = [0]

    async def _execute(*args: Any, **kwargs: Any) -> MagicMock:
        call_count[0] += 1
        result = MagicMock()

        if call_count[0] == 1:
            # Total count
            result.scalar_one.return_value = total_count
        elif call_count[0] == 2:
            # Verdict breakdown — iterable of (status, count) tuples
            result.__iter__ = MagicMock(return_value=iter(verdict_rows))
        elif call_count[0] == 3:
            # Average scan duration
            result.scalar_one.return_value = avg_duration
        elif call_count[0] == 4:
            # MIME types — iterable of (mime, count) tuples
            result.__iter__ = MagicMock(return_value=iter(mime_rows))
        else:
            # Findings
            result.__iter__ = MagicMock(return_value=iter(findings_rows))

        return result

    session.execute = _execute
    return session


class TestAggregateMetrics:
    @pytest.mark.asyncio
    async def test_returns_report_payload(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock()

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert isinstance(result, ReportPayload)

    @pytest.mark.asyncio
    async def test_file_count_from_db(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(total_count=42)

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.file_count == 42

    @pytest.mark.asyncio
    async def test_verdict_breakdown_from_db(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(
            total_count=20,
            verdict_rows=[("clean", 15), ("flagged", 3), ("rejected", 2)],
        )

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.verdict_breakdown.clean == 15
        assert result.verdict_breakdown.flagged == 3
        assert result.verdict_breakdown.rejected == 2

    @pytest.mark.asyncio
    async def test_missing_verdict_statuses_default_to_zero(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        # Only "clean" returned — "flagged" and "rejected" are absent
        session = _make_async_session_mock(
            total_count=5,
            verdict_rows=[("clean", 5)],
        )

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.verdict_breakdown.clean == 5
        assert result.verdict_breakdown.flagged == 0
        assert result.verdict_breakdown.rejected == 0

    @pytest.mark.asyncio
    async def test_average_scan_duration_from_db(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(avg_duration=123.4)

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.average_scan_duration_ms == pytest.approx(123.4)

    @pytest.mark.asyncio
    async def test_none_avg_duration_becomes_zero(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(avg_duration=None)  # type: ignore[arg-type]

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.average_scan_duration_ms == 0.0

    @pytest.mark.asyncio
    async def test_pii_hits_aggregated_from_findings(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(
            findings_rows=[
                ([{"category": "EMAIL"}, {"category": "NI_NUMBER"}],),
                ([{"category": "EMAIL"}],),
                ([],),
            ]
        )

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.pii_hits_by_category.get("EMAIL") == 2
        assert result.pii_hits_by_category.get("NI_NUMBER") == 1

    @pytest.mark.asyncio
    async def test_empty_findings_not_counted(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(findings_rows=[([],)])

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.pii_hits_by_category == {}

    @pytest.mark.asyncio
    async def test_findings_without_category_key_ignored(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        # Finding dict has no 'category' key
        session = _make_async_session_mock(
            findings_rows=[([{"type": "av_threat", "severity": "critical"}],)]
        )

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.pii_hits_by_category == {}

    @pytest.mark.asyncio
    async def test_top_file_types_populated(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock(
            mime_rows=[("application/pdf", 50), ("text/csv", 25)]
        )

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.top_file_types["application/pdf"] == 50
        assert result.top_file_types["text/csv"] == 25

    @pytest.mark.asyncio
    async def test_period_and_tenant_propagated_to_payload(self) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        session = _make_async_session_mock()

        result = await svc.aggregate_metrics(
            session, _TENANT_ID, _PERIOD_START, _PERIOD_END
        )

        assert result.tenant_id == _TENANT_ID
        assert result.period_start == _PERIOD_START
        assert result.period_end == _PERIOD_END


# ---------------------------------------------------------------------------
# ReportService.generate_and_store (end-to-end orchestration)
# ---------------------------------------------------------------------------


class TestGenerateAndStore:
    @pytest.mark.asyncio
    async def test_orchestrates_all_steps(self, tmp_path: Any) -> None:
        """generate_and_store calls aggregate, generate, store, and create_record."""
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        mock_report = _make_report_record()

        with (
            patch.object(svc, "aggregate_metrics", new_callable=AsyncMock, return_value=payload),
            patch.object(svc, "generate_json_report", return_value=b'{"test": true}'),
            patch.object(svc, "store_report", return_value="file:///tmp/test.json"),
            patch.object(svc, "create_report_record", new_callable=AsyncMock, return_value=mock_report),
            patch("fileguard.services.reports.AsyncSessionLocal") as mock_session_cls,
        ):
            # Configure the async context manager chain
            mock_session = AsyncMock()
            mock_begin = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_begin.__aenter__ = AsyncMock(return_value=None)
            mock_begin.__aexit__ = AsyncMock(return_value=False)
            mock_session.begin = MagicMock(return_value=mock_begin)
            mock_session_cls.return_value = mock_session

            result = await svc.generate_and_store(
                _TENANT_ID, _PERIOD_START, _PERIOD_END, "json"
            )

        assert result is mock_report
        svc.aggregate_metrics.assert_awaited_once()
        svc.generate_json_report.assert_called_once_with(payload)
        svc.store_report.assert_called_once()
        svc.create_report_record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_pdf_generator_for_pdf_format(self, tmp_path: Any) -> None:
        from fileguard.services.reports import ReportService

        svc = ReportService()
        payload = _make_payload()
        mock_report = _make_report_record(format="pdf")

        with (
            patch.object(svc, "aggregate_metrics", new_callable=AsyncMock, return_value=payload),
            patch.object(svc, "generate_pdf_report", return_value=b"%PDF-1.4"),
            patch.object(svc, "store_report", return_value="file:///tmp/test.pdf"),
            patch.object(svc, "create_report_record", new_callable=AsyncMock, return_value=mock_report),
            patch("fileguard.services.reports.AsyncSessionLocal") as mock_session_cls,
        ):
            mock_session = AsyncMock()
            mock_begin = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_begin.__aenter__ = AsyncMock(return_value=None)
            mock_begin.__aexit__ = AsyncMock(return_value=False)
            mock_session.begin = MagicMock(return_value=mock_begin)
            mock_session_cls.return_value = mock_session

            await svc.generate_and_store(_TENANT_ID, _PERIOD_START, _PERIOD_END, "pdf")

        svc.generate_pdf_report.assert_called_once_with(payload)


# ---------------------------------------------------------------------------
# Celery task: generate_compliance_report
# ---------------------------------------------------------------------------


class TestGenerateComplianceReportTask:
    def test_task_delegates_to_service(self) -> None:
        from fileguard.services.reports import generate_compliance_report

        mock_report = _make_report_record()
        mock_report.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_report.file_uri = "file:///tmp/test.json"

        with patch(
            "fileguard.services.reports.ReportService.generate_and_store",
            new_callable=AsyncMock,
            return_value=mock_report,
        ):
            result = generate_compliance_report.run(
                tenant_id=str(_TENANT_ID),
                period_start=_PERIOD_START.isoformat(),
                period_end=_PERIOD_END.isoformat(),
                fmt="json",
            )

        assert result["report_id"] == "12345678-1234-5678-1234-567812345678"
        assert result["file_uri"] == "file:///tmp/test.json"

    def test_task_retries_on_exception(self) -> None:
        from celery.exceptions import Retry
        from fileguard.services.reports import generate_compliance_report

        with patch(
            "fileguard.services.reports.ReportService.generate_and_store",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ):
            with pytest.raises((Retry, RuntimeError)):
                generate_compliance_report.run(
                    tenant_id=str(_TENANT_ID),
                    period_start=_PERIOD_START.isoformat(),
                    period_end=_PERIOD_END.isoformat(),
                    fmt="json",
                )


# ---------------------------------------------------------------------------
# Celery task: generate_scheduled_reports
# ---------------------------------------------------------------------------


class TestGenerateScheduledReportsTask:
    def test_dispatches_tasks_for_each_tenant(self) -> None:
        from fileguard.services.reports import generate_scheduled_reports

        tenant_ids = [uuid.uuid4(), uuid.uuid4()]

        with (
            patch(
                "fileguard.services.reports._fetch_all_tenant_ids",
                new_callable=AsyncMock,
                return_value=tenant_ids,
            ),
            patch(
                "fileguard.services.reports.generate_compliance_report"
            ) as mock_task,
        ):
            mock_task.delay = MagicMock()
            result = generate_scheduled_reports.run()

        # Should dispatch 2 tenants × 2 formats = 4 tasks
        assert mock_task.delay.call_count == 4
        assert result["tenants_processed"] == 2

    def test_returns_period_info(self) -> None:
        from fileguard.services.reports import generate_scheduled_reports

        with (
            patch(
                "fileguard.services.reports._fetch_all_tenant_ids",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("fileguard.services.reports.generate_compliance_report") as mock_task,
        ):
            mock_task.delay = MagicMock()
            result = generate_scheduled_reports.run()

        assert "period" in result
        assert "start" in result["period"]
        assert "end" in result["period"]

    def test_no_tasks_dispatched_when_no_tenants(self) -> None:
        from fileguard.services.reports import generate_scheduled_reports

        with (
            patch(
                "fileguard.services.reports._fetch_all_tenant_ids",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("fileguard.services.reports.generate_compliance_report") as mock_task,
        ):
            mock_task.delay = MagicMock()
            result = generate_scheduled_reports.run()

        mock_task.delay.assert_not_called()
        assert result["tenants_processed"] == 0
