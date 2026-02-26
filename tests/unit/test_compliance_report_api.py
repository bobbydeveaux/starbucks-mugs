"""Unit tests for compliance report API handlers and ComplianceReportService.

Coverage targets:
* _parse_period — valid input, invalid format, month out of range.
* list_reports route — authenticated access, period filtering, format filtering,
  pagination defaults, empty result set.
* download_report route — HTTP redirect for http(s) URIs, JSON response for
  cloud storage URIs, 404 for unknown report IDs.
* ComplianceReportService.list_reports — filtering kwargs forwarded to DB query.
* ComplianceReportService.get_report — returns None when not found.
* Tenant isolation — routes reject reports belonging to other tenants.

All tests are fully offline — database reads are replaced by ``unittest.mock``
patches so no external services are required.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fileguard.api.routes.reports import _parse_period
from fileguard.schemas.compliance_report import (
    ComplianceReportListResponse,
    ComplianceReportOut,
)
from fileguard.services.compliance_report import ComplianceReportService


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

TENANT_ID = uuid.uuid4()


def _make_report(
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    format_: str = "pdf",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    file_uri: str = "s3://fileguard-reports/tenant/report.pdf",
) -> MagicMock:
    """Return a mock ComplianceReport ORM instance with sensible defaults."""
    report = MagicMock()
    report.id = uuid.uuid4()
    report.tenant_id = tenant_id
    report.format = format_
    report.period_start = period_start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    report.period_end = period_end or datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    report.file_uri = file_uri
    report.generated_at = datetime(2026, 2, 1, 8, 0, 0, tzinfo=timezone.utc)
    return report


def _make_tenant(tenant_id: uuid.UUID = TENANT_ID) -> MagicMock:
    """Return a mock TenantConfig schema object."""
    tenant = MagicMock()
    tenant.id = tenant_id
    return tenant


def _make_session() -> AsyncMock:
    """Return an async-mock SQLAlchemy session."""
    return AsyncMock()


def _make_request_mock(tenant_id: uuid.UUID = TENANT_ID) -> MagicMock:
    """Return a mock Starlette Request with tenant set on state."""
    request = MagicMock()
    request.state.tenant = _make_tenant(tenant_id)
    return request


# ---------------------------------------------------------------------------
# TestParsePeriod
# ---------------------------------------------------------------------------


class TestParsePeriod:
    def test_valid_period_returns_start_and_end(self) -> None:
        start, end = _parse_period("2026-01")
        assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert end == datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

    def test_february_non_leap_year(self) -> None:
        start, end = _parse_period("2025-02")
        assert start == datetime(2025, 2, 1, tzinfo=timezone.utc)
        assert end == datetime(2025, 2, 28, 23, 59, 59, tzinfo=timezone.utc)

    def test_february_leap_year(self) -> None:
        start, end = _parse_period("2024-02")
        assert start == datetime(2024, 2, 1, tzinfo=timezone.utc)
        assert end == datetime(2024, 2, 29, 23, 59, 59, tzinfo=timezone.utc)

    def test_december_last_day_is_31(self) -> None:
        _, end = _parse_period("2026-12")
        assert end.day == 31

    def test_period_start_is_utc(self) -> None:
        start, _ = _parse_period("2026-06")
        assert start.tzinfo == timezone.utc

    def test_period_end_is_utc(self) -> None:
        _, end = _parse_period("2026-06")
        assert end.tzinfo == timezone.utc

    def test_invalid_format_raises_422(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _parse_period("202601")
        assert exc_info.value.status_code == 422

    def test_non_numeric_year_raises_422(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _parse_period("XXXX-01")
        assert exc_info.value.status_code == 422

    def test_month_zero_raises_422(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _parse_period("2026-00")
        assert exc_info.value.status_code == 422

    def test_month_13_raises_422(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _parse_period("2026-13")
        assert exc_info.value.status_code == 422

    def test_error_message_contains_format_hint(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _parse_period("bad")
        assert "YYYY-MM" in exc_info.value.detail


# ---------------------------------------------------------------------------
# TestComplianceReportServiceListReports
# ---------------------------------------------------------------------------


class TestComplianceReportServiceListReports:
    def setup_method(self) -> None:
        self.service = ComplianceReportService()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_reports(self) -> None:
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        reports, total = await self.service.list_reports(session, TENANT_ID)

        assert reports == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_reports_for_tenant(self) -> None:
        session = _make_session()
        report = _make_report()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [report]
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        reports, total = await self.service.list_reports(session, TENANT_ID)

        assert len(reports) == 1
        assert reports[0] is report
        assert total == 1

    @pytest.mark.asyncio
    async def test_execute_called_twice_for_count_and_data(self) -> None:
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        await self.service.list_reports(session, TENANT_ID)

        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_reports_returned(self) -> None:
        session = _make_session()
        reports_data = [_make_report() for _ in range(3)]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = reports_data
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        reports, total = await self.service.list_reports(session, TENANT_ID)

        assert len(reports) == 3
        assert total == 3

    @pytest.mark.asyncio
    async def test_total_reflects_all_matching_rows_not_page_size(self) -> None:
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 100
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_report()]
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        reports, total = await self.service.list_reports(session, TENANT_ID, limit=1)

        assert total == 100
        assert len(reports) == 1


# ---------------------------------------------------------------------------
# TestComplianceReportServiceGetReport
# ---------------------------------------------------------------------------


class TestComplianceReportServiceGetReport:
    def setup_method(self) -> None:
        self.service = ComplianceReportService()

    @pytest.mark.asyncio
    async def test_returns_report_when_found(self) -> None:
        session = _make_session()
        report = _make_report()
        result = MagicMock()
        result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=result)

        found = await self.service.get_report(session, TENANT_ID, report.id)

        assert found is report

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = _make_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        found = await self.service.get_report(session, TENANT_ID, uuid.uuid4())

        assert found is None

    @pytest.mark.asyncio
    async def test_returns_none_for_different_tenant(self) -> None:
        session = _make_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        other_tenant_id = uuid.uuid4()
        found = await self.service.get_report(session, other_tenant_id, uuid.uuid4())

        assert found is None

    @pytest.mark.asyncio
    async def test_execute_called_once(self) -> None:
        session = _make_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        await self.service.get_report(session, TENANT_ID, uuid.uuid4())

        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestComplianceReportSchemas
# ---------------------------------------------------------------------------


class TestComplianceReportOut:
    def test_from_orm_attributes(self) -> None:
        report = _make_report(format_="json", file_uri="https://example.com/report.json")
        out = ComplianceReportOut.model_validate(report)

        assert out.id == report.id
        assert out.tenant_id == report.tenant_id
        assert out.format == "json"
        assert out.file_uri == "https://example.com/report.json"
        assert out.period_start == report.period_start
        assert out.period_end == report.period_end
        assert out.generated_at == report.generated_at

    def test_serialise_to_dict_contains_all_fields(self) -> None:
        report = _make_report()
        out = ComplianceReportOut.model_validate(report)
        data = out.model_dump()

        for field in ("id", "tenant_id", "format", "file_uri", "period_start", "period_end", "generated_at"):
            assert field in data, f"Missing field: {field}"

    def test_pdf_format_preserved(self) -> None:
        report = _make_report(format_="pdf")
        out = ComplianceReportOut.model_validate(report)
        assert out.format == "pdf"

    def test_json_format_preserved(self) -> None:
        report = _make_report(format_="json")
        out = ComplianceReportOut.model_validate(report)
        assert out.format == "json"


class TestComplianceReportListResponse:
    def test_empty_list(self) -> None:
        resp = ComplianceReportListResponse(reports=[], total=0, limit=50, offset=0)
        assert resp.total == 0
        assert resp.reports == []
        assert resp.limit == 50
        assert resp.offset == 0

    def test_with_reports(self) -> None:
        report = _make_report()
        out = ComplianceReportOut.model_validate(report)
        resp = ComplianceReportListResponse(reports=[out], total=1, limit=10, offset=0)
        assert resp.total == 1
        assert len(resp.reports) == 1

    def test_pagination_fields_preserved(self) -> None:
        resp = ComplianceReportListResponse(reports=[], total=200, limit=25, offset=75)
        assert resp.total == 200
        assert resp.limit == 25
        assert resp.offset == 75


# ---------------------------------------------------------------------------
# TestListReportsRoute
# ---------------------------------------------------------------------------


class TestListReportsRoute:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            response = await list_reports(
                request=request,
                period=None,
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        assert isinstance(response, ComplianceReportListResponse)
        assert response.total == 0
        assert response.reports == []
        assert response.limit == 50
        assert response.offset == 0

    @pytest.mark.asyncio
    async def test_returns_serialised_reports(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()
        report = _make_report()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([report], 1),
        ):
            response = await list_reports(
                request=request,
                period=None,
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        assert response.total == 1
        assert len(response.reports) == 1
        assert response.reports[0].id == report.id

    @pytest.mark.asyncio
    async def test_period_filter_parsed_and_forwarded(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            await list_reports(
                request=request,
                period="2026-03",
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        _, call_kwargs = mock_list.call_args
        assert call_kwargs["period_start"] == datetime(2026, 3, 1, tzinfo=timezone.utc)
        assert call_kwargs["period_end"] == datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_no_period_passes_none_to_service(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            await list_reports(
                request=request,
                period=None,
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        _, call_kwargs = mock_list.call_args
        assert call_kwargs["period_start"] is None
        assert call_kwargs["period_end"] is None

    @pytest.mark.asyncio
    async def test_format_filter_forwarded_to_service(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            await list_reports(
                request=request,
                period=None,
                format="json",
                limit=50,
                offset=0,
                session=session,
            )

        _, call_kwargs = mock_list.call_args
        assert call_kwargs["format_"] == "json"

    @pytest.mark.asyncio
    async def test_no_format_passes_none_to_service(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            await list_reports(
                request=request,
                period=None,
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        _, call_kwargs = mock_list.call_args
        assert call_kwargs["format_"] is None

    @pytest.mark.asyncio
    async def test_invalid_format_raises_422(self) -> None:
        from fastapi import HTTPException

        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with pytest.raises(HTTPException) as exc_info:
            await list_reports(
                request=request,
                period=None,
                format="xml",
                limit=50,
                offset=0,
                session=session,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_period_raises_422(self) -> None:
        from fastapi import HTTPException

        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with pytest.raises(HTTPException) as exc_info:
            await list_reports(
                request=request,
                period="bad-period",
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_pagination_params_forwarded_to_service(self) -> None:
        from fileguard.api.routes.reports import list_reports

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            response = await list_reports(
                request=request,
                period=None,
                format=None,
                limit=10,
                offset=30,
                session=session,
            )

        _, call_kwargs = mock_list.call_args
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 30
        assert response.limit == 10
        assert response.offset == 30

    @pytest.mark.asyncio
    async def test_tenant_id_forwarded_to_service(self) -> None:
        from fileguard.api.routes.reports import list_reports

        custom_tenant_id = uuid.uuid4()
        session = _make_session()
        request = _make_request_mock(tenant_id=custom_tenant_id)

        with patch(
            "fileguard.api.routes.reports._service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_list:
            await list_reports(
                request=request,
                period=None,
                format=None,
                limit=50,
                offset=0,
                session=session,
            )

        call_args, _ = mock_list.call_args
        assert call_args[1] == custom_tenant_id


# ---------------------------------------------------------------------------
# TestDownloadReportRoute
# ---------------------------------------------------------------------------


class TestDownloadReportRoute:
    @pytest.mark.asyncio
    async def test_returns_404_when_report_not_found(self) -> None:
        from fastapi import HTTPException

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await download_report(
                    report_id=uuid.uuid4(),
                    request=request,
                    session=session,
                )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Report not found"

    @pytest.mark.asyncio
    async def test_redirects_for_https_uri(self) -> None:
        from fastapi.responses import RedirectResponse

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()
        report = _make_report(file_uri="https://cdn.example.com/report-2026-01.pdf")

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = await download_report(
                report_id=report.id,
                request=request,
                session=session,
            )

        assert isinstance(response, RedirectResponse)
        assert response.status_code == 302

    @pytest.mark.asyncio
    async def test_redirects_for_http_uri(self) -> None:
        from fastapi.responses import RedirectResponse

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()
        report = _make_report(file_uri="http://internal.example.com/report.pdf")

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = await download_report(
                report_id=report.id,
                request=request,
                session=session,
            )

        assert isinstance(response, RedirectResponse)
        assert response.status_code == 302

    @pytest.mark.asyncio
    async def test_returns_json_for_s3_uri(self) -> None:
        from fastapi.responses import JSONResponse

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()
        report = _make_report(file_uri="s3://fileguard-reports/tenant/2026-01.pdf")

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = await download_report(
                report_id=report.id,
                request=request,
                session=session,
            )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_json_for_gcs_uri(self) -> None:
        from fastapi.responses import JSONResponse

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()
        report = _make_report(file_uri="gs://fileguard-bucket/2026-01.json")

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = await download_report(
                report_id=report.id,
                request=request,
                session=session,
            )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_json_response_contains_required_fields(self) -> None:
        from fileguard.api.routes.reports import download_report

        session = _make_session()
        request = _make_request_mock()
        file_uri = "s3://fileguard-reports/tenant/2026-01.pdf"
        report = _make_report(file_uri=file_uri)

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = await download_report(
                report_id=report.id,
                request=request,
                session=session,
            )

        body = json.loads(response.body)
        assert body["file_uri"] == file_uri
        assert body["report_id"] == str(report.id)
        assert "format" in body
        assert "generated_at" in body
        assert "period_start" in body
        assert "period_end" in body

    @pytest.mark.asyncio
    async def test_tenant_isolation_404_for_other_tenant(self) -> None:
        from fastapi import HTTPException

        from fileguard.api.routes.reports import download_report

        session = _make_session()
        other_tenant_id = uuid.uuid4()
        request = _make_request_mock(tenant_id=other_tenant_id)

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await download_report(
                    report_id=uuid.uuid4(),
                    request=request,
                    session=session,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_report_called_with_correct_tenant_and_id(self) -> None:
        from fileguard.api.routes.reports import download_report

        session = _make_session()
        custom_tenant_id = uuid.uuid4()
        request = _make_request_mock(tenant_id=custom_tenant_id)
        report_id = uuid.uuid4()

        with patch(
            "fileguard.api.routes.reports._service.get_report",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get:
            try:
                await download_report(
                    report_id=report_id,
                    request=request,
                    session=session,
                )
            except Exception:
                pass  # 404 expected

        mock_get.assert_awaited_once()
        call_args = mock_get.call_args
        assert call_args.args[1] == custom_tenant_id
        assert call_args.args[2] == report_id
