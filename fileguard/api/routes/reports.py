"""API routes for compliance report retrieval.

Endpoints
---------
GET  /v1/reports
    List compliance reports for the authenticated tenant, with optional
    filtering by reporting period (``period=YYYY-MM``) and format
    (``format=pdf|json``).  Results are paginated via ``limit`` and ``offset``
    query parameters.

GET  /v1/reports/{report_id}/download
    Retrieve a single compliance report and redirect to its file.  For HTTP(S)
    file URIs a ``302 Found`` redirect is returned.  For cloud storage URIs
    (``s3://``, ``gs://``) the file location metadata is returned as JSON so
    that the caller can obtain temporary credentials or signed URLs
    independently.

All endpoints require ``Authorization: Bearer <token>`` authentication
(handled by :class:`~fileguard.api.middleware.auth.AuthMiddleware`).
Tenant isolation is enforced at the query layer — callers can only access
reports that belong to their own tenant.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from fileguard.db.session import get_db
from fileguard.schemas.compliance_report import (
    ComplianceReportListResponse,
    ComplianceReportOut,
)
from fileguard.services.compliance_report import ComplianceReportService

router = APIRouter(prefix="/v1/reports", tags=["compliance-reports"])

_service = ComplianceReportService()


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Parse a ``YYYY-MM`` period string into UTC period_start / period_end datetimes.

    Args:
        period: Reporting period string in ``YYYY-MM`` format.

    Returns:
        A ``(period_start, period_end)`` tuple representing the first and last
        instant of the given calendar month in UTC.

    Raises:
        :class:`fastapi.HTTPException`: 422 if *period* cannot be parsed as
            ``YYYY-MM``.
    """
    try:
        if len(period) != 7 or period[4] != "-":
            raise ValueError("bad format")
        year = int(period[:4])
        month = int(period[5:7])
        if not (1 <= month <= 12):
            raise ValueError("month out of range")
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=422,
            detail="period must be in YYYY-MM format (e.g. '2026-01')",
        )

    _, last_day = calendar.monthrange(year, month)
    period_start = datetime(year, month, 1, tzinfo=timezone.utc)
    period_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return period_start, period_end


@router.get("", response_model=ComplianceReportListResponse)
async def list_reports(
    request: Request,
    period: Annotated[
        str | None,
        Query(description="Reporting period in YYYY-MM format (e.g. '2026-01')"),
    ] = None,
    format: Annotated[
        str | None,
        Query(description="Report format filter: 'pdf' or 'json'"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1–100)")] = 50,
    offset: Annotated[int, Query(ge=0, description="Zero-based page offset")] = 0,
    session: AsyncSession = Depends(get_db),
) -> ComplianceReportListResponse:
    """List compliance reports for the authenticated tenant.

    Supports optional filtering by:

    - ``period`` — calendar month in ``YYYY-MM`` format; matches reports whose
      ``period_start`` falls within that month.
    - ``format`` — ``"pdf"`` or ``"json"``.

    Results are ordered by ``generated_at`` descending (most recent first) and
    paginated via ``limit`` / ``offset``.

    **Example**

        GET /v1/reports?period=2026-01&format=pdf&limit=10
    """
    tenant = request.state.tenant

    period_start: datetime | None = None
    period_end: datetime | None = None
    if period is not None:
        period_start, period_end = _parse_period(period)

    if format is not None and format not in ("pdf", "json"):
        raise HTTPException(
            status_code=422,
            detail="format must be 'pdf' or 'json'",
        )

    reports, total = await _service.list_reports(
        session,
        tenant.id,
        period_start=period_start,
        period_end=period_end,
        format_=format,
        limit=limit,
        offset=offset,
    )

    return ComplianceReportListResponse(
        reports=[ComplianceReportOut.model_validate(r) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Retrieve a compliance report and redirect to its file.

    Returns a ``302 Found`` redirect when the report's ``file_uri`` is an
    HTTP or HTTPS URL (e.g. a pre-signed S3 URL or a GCS signed URL).

    For cloud storage URIs (``s3://``, ``gs://``) — which require the caller
    to exchange for a signed URL using their own credentials — a ``200 OK``
    JSON response is returned containing the ``file_uri`` and report metadata.

    Returns ``404 Not Found`` if no report with *report_id* exists for the
    authenticated tenant.
    """
    tenant = request.state.tenant

    report = await _service.get_report(session, tenant.id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    file_uri: str = report.file_uri

    if file_uri.startswith(("http://", "https://")):
        return RedirectResponse(url=file_uri, status_code=302)

    # Cloud storage URIs (s3://, gs://) cannot be served directly; return
    # metadata so the caller can obtain a signed URL using their own credentials.
    body: dict[str, Any] = {
        "report_id": str(report.id),
        "file_uri": file_uri,
        "format": report.format,
        "generated_at": report.generated_at.isoformat(),
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
    }
    return JSONResponse(content=body, status_code=200)
