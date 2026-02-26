"""FastAPI handlers for compliance report retrieval and download.

Endpoints
---------
GET /v1/reports
    Return a paginated, tenant-scoped list of compliance report metadata.
    Supports optional ``start_date`` / ``end_date`` query parameters to
    filter by report period and ``format`` to filter by report format.

GET /v1/reports/{report_id}/download
    Stream the stored report artifact (PDF or JSON).  The response
    Content-Type is determined in priority order:

    1. ``format`` query parameter (``pdf`` or ``json``)
    2. ``Accept`` request header (``application/pdf`` or ``application/json``)
    3. The ``format`` stored on the ``ComplianceReport`` row

    Returns 404 when the report ID does not exist **or** belongs to a
    different tenant (cross-tenant isolation).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.db.session import get_db
from fileguard.models.compliance_report import ComplianceReport
from fileguard.schemas.report import ReportListResponse, ReportSummary
from fileguard.schemas.tenant import TenantConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tenant(request: Request) -> TenantConfig:
    """Return the authenticated tenant attached by AuthMiddleware."""
    return request.state.tenant  # type: ignore[no-any-return]


def _accept_to_format(accept: str) -> str | None:
    """Map an ``Accept`` header value to a ``format`` string.

    Returns ``"pdf"``, ``"json"``, or ``None`` when the header does not
    express a preference for either format.
    """
    if "application/pdf" in accept:
        return "pdf"
    if "application/json" in accept:
        return "json"
    return None


def _read_report_file(uri: str) -> bytes:
    """Read binary content from a local file-system path.

    The ``file_uri`` column may contain a plain path or a ``file://``-prefixed
    URI.  Cloud storage URIs (``s3://``, ``gs://``) would be handled by an
    injected storage service in production; this implementation covers the
    local and test cases used by the integration test suite.

    Raises:
        FileNotFoundError: If the file does not exist at the resolved path.
        OSError: On any other I/O error.
    """
    if uri.startswith("file://"):
        path = uri[len("file://"):]
    else:
        path = uri

    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# GET /v1/reports
# ---------------------------------------------------------------------------


@router.get("", response_model=ReportListResponse)
async def list_reports(
    request: Request,
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Records per page")] = 20,
    format: Annotated[  # noqa: A002
        str | None,
        Query(description="Filter by report format: pdf or json"),
    ] = None,
    start_date: Annotated[
        str | None,
        Query(description="ISO-8601 date: include reports whose period_start >= start_date"),
    ] = None,
    end_date: Annotated[
        str | None,
        Query(description="ISO-8601 date: include reports whose period_end <= end_date"),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> ReportListResponse:
    """Return a paginated list of compliance reports for the authenticated tenant.

    All query parameters are optional.  Without filters the full report
    history for the tenant is returned newest-first.

    Args:
        request: The current HTTP request (tenant extracted from state).
        page: Page number, starting at 1.
        page_size: Number of records per page (max 100).
        format: Optional report format filter (``pdf`` or ``json``).
        start_date: Optional ISO-8601 lower bound on ``period_start``.
        end_date: Optional ISO-8601 upper bound on ``period_end``.
        db: Injected async database session.

    Returns:
        A :class:`ReportListResponse` with ``items``, ``total``, ``page``,
        and ``page_size`` fields.
    """
    tenant: TenantConfig = _get_tenant(request)

    # Base query scoped to the authenticated tenant
    base_stmt = select(ComplianceReport).where(
        ComplianceReport.tenant_id == tenant.id
    )

    # Optional filters
    if format is not None:
        base_stmt = base_stmt.where(ComplianceReport.format == format)

    if start_date is not None:
        try:
            start_dt = datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="start_date must be a valid ISO-8601 date string",
            )
        base_stmt = base_stmt.where(ComplianceReport.period_start >= start_dt)

    if end_date is not None:
        try:
            end_dt = datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="end_date must be a valid ISO-8601 date string",
            )
        base_stmt = base_stmt.where(ComplianceReport.period_end <= end_dt)

    # Count total matching records (without pagination)
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    # Apply ordering and pagination
    offset = (page - 1) * page_size
    page_stmt = (
        base_stmt
        .order_by(ComplianceReport.generated_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(page_stmt)
    reports = result.scalars().all()

    items = [ReportSummary.model_validate(r) for r in reports]
    return ReportListResponse(items=items, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# GET /v1/reports/{report_id}/download
# ---------------------------------------------------------------------------


@router.get("/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    request: Request,
    format: Annotated[  # noqa: A002
        str | None,
        Query(description="Override output format: pdf or json"),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download a compliance report file.

    The response Content-Type is resolved in this order:

    1. ``format`` query parameter
    2. ``Accept`` request header
    3. The ``format`` column stored on the report row

    Returns 200 with the file content on success.  Returns 404 when the
    report ID does not exist or belongs to a different tenant.

    Args:
        report_id: UUID of the report to download.
        request: The current HTTP request (tenant extracted from state).
        format: Optional format override (``pdf`` or ``json``).
        db: Injected async database session.

    Returns:
        A :class:`~fastapi.responses.Response` with appropriate
        ``Content-Type`` and ``Content-Disposition`` headers.

    Raises:
        HTTPException(404): Report not found or belongs to another tenant.
        HTTPException(404): Stored report file is missing from the file system.
        HTTPException(500): Unexpected error reading the report file.
    """
    tenant: TenantConfig = _get_tenant(request)

    # Fetch report, enforcing tenant scope for cross-tenant isolation
    stmt = select(ComplianceReport).where(
        ComplianceReport.id == report_id,
        ComplianceReport.tenant_id == tenant.id,
    )
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    # Resolve the requested format
    accept_header = request.headers.get("Accept", "")
    resolved_format: str = (
        format
        or _accept_to_format(accept_header)
        or report.format
    )

    # Read the report file from its stored URI
    try:
        content = _read_report_file(str(report.file_uri))
    except FileNotFoundError:
        logger.warning(
            "Report file not found on disk: report_id=%s uri=%s",
            report_id,
            report.file_uri,
        )
        raise HTTPException(status_code=404, detail="Report file not found")
    except OSError as exc:
        logger.error(
            "Failed to read report file: report_id=%s uri=%s error=%s",
            report_id,
            report.file_uri,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to read report file")

    if resolved_format == "pdf":
        media_type = "application/pdf"
        filename = f"report-{report_id}.pdf"
    else:
        media_type = "application/json"
        filename = f"report-{report_id}.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
