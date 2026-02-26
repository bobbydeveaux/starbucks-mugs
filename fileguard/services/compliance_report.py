"""ComplianceReportService — read-only access to compliance report records.

Usage::

    from fileguard.services.compliance_report import ComplianceReportService

    service = ComplianceReportService()

    async with AsyncSessionLocal() as session:
        reports, total = await service.list_reports(
            session,
            tenant_id=tenant.id,
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc),
            format_="pdf",
            limit=50,
            offset=0,
        )

        report = await service.get_report(session, tenant_id=tenant.id, report_id=report_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.models.compliance_report import ComplianceReport


class ComplianceReportService:
    """Read-only service for listing and retrieving compliance report metadata.

    All queries are automatically scoped to the authenticated tenant via
    ``tenant_id`` to enforce data isolation between tenants.
    """

    async def list_reports(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        format_: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ComplianceReport], int]:
        """Return a paginated list of compliance reports for *tenant_id*.

        Filtering is performed server-side.  When *period_start* is provided,
        only reports with ``period_start >= period_start`` are returned.  When
        *period_end* is provided, only reports with ``period_end <= period_end``
        are returned.  Both can be combined to restrict results to a specific
        calendar month.

        Args:
            session: Open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
            tenant_id: UUID of the authenticated tenant — used for strict
                row-level tenant isolation.
            period_start: Inclusive lower bound on ``ComplianceReport.period_start``.
            period_end: Inclusive upper bound on ``ComplianceReport.period_end``.
            format_: Optional format filter — ``"pdf"`` or ``"json"``.
            limit: Maximum number of records to return (1–100).
            offset: Zero-based page offset.

        Returns:
            A 2-tuple of ``(records, total_count)`` where *records* is the
            current page and *total_count* is the total number of matching rows
            across all pages.
        """
        base_query = select(ComplianceReport).where(
            ComplianceReport.tenant_id == tenant_id
        )

        if period_start is not None:
            base_query = base_query.where(ComplianceReport.period_start >= period_start)
        if period_end is not None:
            base_query = base_query.where(ComplianceReport.period_end <= period_end)
        if format_ is not None:
            base_query = base_query.where(ComplianceReport.format == format_)

        # Count total matching rows before applying pagination
        count_query = select(func.count()).select_from(base_query.subquery())
        total: int = (await session.execute(count_query)).scalar_one()

        # Apply ordering and pagination
        paged_query = (
            base_query
            .order_by(ComplianceReport.generated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows: Sequence[ComplianceReport] = (await session.execute(paged_query)).scalars().all()

        return rows, total

    async def get_report(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        report_id: uuid.UUID,
    ) -> ComplianceReport | None:
        """Return a single compliance report by *report_id*, scoped to *tenant_id*.

        Args:
            session: Open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
            tenant_id: UUID of the authenticated tenant — ensures a tenant
                cannot access another tenant's reports.
            report_id: UUID of the compliance report to retrieve.

        Returns:
            The matching :class:`~fileguard.models.compliance_report.ComplianceReport`
            instance, or ``None`` if no matching record exists for this tenant.
        """
        result = await session.execute(
            select(ComplianceReport).where(
                ComplianceReport.id == report_id,
                ComplianceReport.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()
