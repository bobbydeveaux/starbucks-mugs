"""ComplianceReportService — aggregation and generation of compliance reports.

This module contains:

* :class:`ReportService` — the core service that queries ``scan_event``
  records, aggregates metrics (file counts, verdict breakdown, PII hits by
  category), generates JSON or PDF output, persists the file to the configured
  storage directory, and inserts a ``compliance_report`` row into PostgreSQL.

* :func:`generate_compliance_report` — Celery task wrapping
  :meth:`ReportService.generate_and_store` for a single tenant/period.

* :func:`generate_scheduled_reports` — Celery beat task that discovers all
  active tenants and fans out individual ``generate_compliance_report`` tasks
  covering the previous reporting period (daily or weekly depending on
  ``settings.REPORT_CADENCE``).

Database access inside Celery tasks uses :func:`asyncio.run` to drive the
existing :data:`~fileguard.db.session.AsyncSessionLocal` from a synchronous
task worker.

Usage (triggering a report manually)::

    from fileguard.services.reports import generate_compliance_report

    generate_compliance_report.delay(
        tenant_id="<uuid>",
        period_start="2026-02-01T00:00:00+00:00",
        period_end="2026-03-01T00:00:00+00:00",
        fmt="json",
    )
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.celery_app import celery_app
from fileguard.config import settings
from fileguard.db.session import AsyncSessionLocal
from fileguard.models.compliance_report import ComplianceReport
from fileguard.models.scan_event import ScanEvent
from fileguard.models.tenant_config import TenantConfig
from fileguard.schemas.report import ReportPayload, VerdictBreakdown

logger = logging.getLogger(__name__)


class ReportService:
    """Service for generating and persisting compliance reports.

    All database access is performed via an :class:`~sqlalchemy.ext.asyncio.AsyncSession`
    supplied by the caller (or obtained internally via :data:`~fileguard.db.session.AsyncSessionLocal`).

    Typical usage::

        service = ReportService()
        report = await service.generate_and_store(
            tenant_id=UUID("..."),
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            fmt="json",
        )
    """

    # ------------------------------------------------------------------
    # Metric aggregation
    # ------------------------------------------------------------------

    async def aggregate_metrics(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> ReportPayload:
        """Query ``scan_event`` rows within the period and compute metrics.

        Args:
            session: Open async SQLAlchemy session (read-only queries).
            tenant_id: The tenant whose events to aggregate.
            period_start: Inclusive lower bound of the report period.
            period_end: Exclusive upper bound of the report period.

        Returns:
            A fully-populated :class:`~fileguard.schemas.report.ReportPayload`.
        """
        # -- Total file count -----------------------------------------------
        total_result = await session.execute(
            select(func.count(ScanEvent.id)).where(
                ScanEvent.tenant_id == tenant_id,
                ScanEvent.created_at >= period_start,
                ScanEvent.created_at < period_end,
            )
        )
        file_count: int = total_result.scalar_one() or 0

        # -- Verdict breakdown -----------------------------------------------
        verdict_result = await session.execute(
            select(ScanEvent.status, func.count(ScanEvent.id))
            .where(
                ScanEvent.tenant_id == tenant_id,
                ScanEvent.created_at >= period_start,
                ScanEvent.created_at < period_end,
            )
            .group_by(ScanEvent.status)
        )
        verdict_counts: dict[str, int] = {row[0]: row[1] for row in verdict_result}
        verdict = VerdictBreakdown(
            clean=verdict_counts.get("clean", 0),
            flagged=verdict_counts.get("flagged", 0),
            rejected=verdict_counts.get("rejected", 0),
        )

        # -- Average scan duration ------------------------------------------
        avg_result = await session.execute(
            select(func.avg(ScanEvent.scan_duration_ms)).where(
                ScanEvent.tenant_id == tenant_id,
                ScanEvent.created_at >= period_start,
                ScanEvent.created_at < period_end,
            )
        )
        average_scan_duration_ms: float = float(avg_result.scalar_one() or 0.0)

        # -- Top MIME types (up to 10) --------------------------------------
        mime_result = await session.execute(
            select(ScanEvent.mime_type, func.count(ScanEvent.id))
            .where(
                ScanEvent.tenant_id == tenant_id,
                ScanEvent.created_at >= period_start,
                ScanEvent.created_at < period_end,
            )
            .group_by(ScanEvent.mime_type)
            .order_by(func.count(ScanEvent.id).desc())
            .limit(10)
        )
        top_file_types: dict[str, int] = {row[0]: row[1] for row in mime_result}

        # -- PII hits by category (Python-side aggregation) -----------------
        # Load all non-empty findings for the period and tally by category.
        findings_result = await session.execute(
            select(ScanEvent.findings).where(
                ScanEvent.tenant_id == tenant_id,
                ScanEvent.created_at >= period_start,
                ScanEvent.created_at < period_end,
            )
        )
        pii_hits_by_category: dict[str, int] = {}
        for (findings,) in findings_result:
            if not findings:
                continue
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                category = finding.get("category")
                if category:
                    pii_hits_by_category[category] = (
                        pii_hits_by_category.get(category, 0) + 1
                    )

        return ReportPayload(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            generated_at=datetime.now(tz=timezone.utc),
            file_count=file_count,
            verdict_breakdown=verdict,
            pii_hits_by_category=pii_hits_by_category,
            top_file_types=top_file_types,
            average_scan_duration_ms=average_scan_duration_ms,
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_json_report(self, payload: ReportPayload) -> bytes:
        """Serialise *payload* to indented UTF-8 JSON bytes.

        Args:
            payload: Aggregated report data.

        Returns:
            JSON-encoded bytes suitable for writing to a ``.json`` file.
        """
        data = payload.model_dump(mode="json")
        return json.dumps(data, indent=2, default=str).encode("utf-8")

    def generate_pdf_report(self, payload: ReportPayload) -> bytes:
        """Generate a PDF compliance report using ReportLab.

        Produces an A4 PDF document containing:

        * Report title, period, generation timestamp, and tenant ID.
        * Summary table: total file count, per-verdict counts, and average
          scan duration.
        * PII hits by category table (if any PII was detected).
        * Top file types table (if any scans were recorded).

        Args:
            payload: Aggregated report data.

        Returns:
            Raw PDF bytes suitable for writing to a ``.pdf`` file.

        Raises:
            ImportError: If ``reportlab`` is not installed.
        """
        from reportlab.lib import colors  # type: ignore[import-untyped]
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
        from reportlab.lib.units import cm  # type: ignore[import-untyped]
        from reportlab.platypus import (  # type: ignore[import-untyped]
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        story: list[Any] = []

        # -- Title & metadata -----------------------------------------------
        story.append(Paragraph("FileGuard Compliance Report", styles["Title"]))
        story.append(Spacer(1, 0.4 * cm))
        story.append(
            Paragraph(
                f"Period: {payload.period_start.date()} to {payload.period_end.date()}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"Generated: {payload.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(f"Tenant ID: {payload.tenant_id}", styles["Normal"])
        )
        story.append(Spacer(1, 0.5 * cm))

        # -- Summary table --------------------------------------------------
        story.append(Paragraph("Summary", styles["Heading2"]))
        summary_data = [
            ["Metric", "Value"],
            ["Total Files Scanned", str(payload.file_count)],
            ["Clean", str(payload.verdict_breakdown.clean)],
            ["Flagged", str(payload.verdict_breakdown.flagged)],
            ["Rejected", str(payload.verdict_breakdown.rejected)],
            [
                "Average Scan Duration (ms)",
                f"{payload.average_scan_duration_ms:.1f}",
            ],
        ]
        _header_style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4A4A4A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ]
        )
        summary_table = Table(summary_data, colWidths=[10 * cm, 6 * cm])
        summary_table.setStyle(_header_style)
        story.append(summary_table)
        story.append(Spacer(1, 0.5 * cm))

        # -- PII hits by category -------------------------------------------
        if payload.pii_hits_by_category:
            story.append(Paragraph("PII Hits by Category", styles["Heading2"]))
            pii_data = [["Category", "Hit Count"]]
            for category, count in sorted(
                payload.pii_hits_by_category.items(), key=lambda x: (-x[1], x[0])
            ):
                pii_data.append([category, str(count)])
            pii_table = Table(pii_data, colWidths=[12 * cm, 4 * cm])
            pii_table.setStyle(_header_style)
            story.append(pii_table)
            story.append(Spacer(1, 0.5 * cm))

        # -- Top file types -------------------------------------------------
        if payload.top_file_types:
            story.append(Paragraph("Top File Types", styles["Heading2"]))
            ft_data = [["MIME Type", "Count"]]
            for mime, count in sorted(
                payload.top_file_types.items(), key=lambda x: -x[1]
            ):
                ft_data.append([mime, str(count)])
            ft_table = Table(ft_data, colWidths=[12 * cm, 4 * cm])
            ft_table.setStyle(_header_style)
            story.append(ft_table)

        doc.build(story)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store_report(
        self,
        content: bytes,
        fmt: str,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> str:
        """Write *content* to the local reports directory and return a URI.

        The output file is placed under ``settings.REPORTS_DIR`` and the
        returned URI uses the ``file://`` scheme.  A future extension could
        upload to S3 / GCS and return an ``s3://`` or ``gs://`` URI instead.

        Args:
            content: Raw file bytes (JSON or PDF).
            fmt: ``"json"`` or ``"pdf"``.
            tenant_id: Tenant UUID used in the filename.
            period_start: Report period start (for filename).
            period_end: Report period end (for filename).

        Returns:
            A ``file://`` URI pointing to the stored file.
        """
        reports_dir = settings.REPORTS_DIR
        os.makedirs(reports_dir, exist_ok=True)

        ext = "pdf" if fmt == "pdf" else "json"
        filename = (
            f"report_{tenant_id}"
            f"_{period_start.strftime('%Y%m%d')}"
            f"_{period_end.strftime('%Y%m%d')}.{ext}"
        )
        file_path = os.path.join(reports_dir, filename)

        with open(file_path, "wb") as fh:
            fh.write(content)

        return f"file://{file_path}"

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    async def create_report_record(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        fmt: str,
        file_uri: str,
        generated_at: datetime,
    ) -> ComplianceReport:
        """Insert a ``compliance_report`` row and flush within the transaction.

        Args:
            session: Open async session with an active transaction.
            tenant_id: Report tenant.
            period_start: Report period start.
            period_end: Report period end.
            fmt: ``"json"`` or ``"pdf"``.
            file_uri: URI where the report file is stored.
            generated_at: Timestamp of report generation.

        Returns:
            The newly inserted :class:`~fileguard.models.compliance_report.ComplianceReport`
            instance (attached to *session*).
        """
        report = ComplianceReport(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            format=fmt,
            file_uri=file_uri,
            generated_at=generated_at,
        )
        session.add(report)
        await session.flush()
        return report

    # ------------------------------------------------------------------
    # End-to-end orchestration
    # ------------------------------------------------------------------

    async def generate_and_store(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        fmt: str = "json",
    ) -> ComplianceReport:
        """Aggregate metrics, generate report, store file, and persist DB row.

        This is the main entry point for report generation.  It opens its own
        database session and transaction.

        Args:
            tenant_id: The tenant for whom to generate the report.
            period_start: Report period start (inclusive).
            period_end: Report period end (exclusive).
            fmt: Output format — ``"json"`` or ``"pdf"``.

        Returns:
            The persisted :class:`~fileguard.models.compliance_report.ComplianceReport`
            row with its generated ``id`` and ``generated_at`` values.
        """
        async with AsyncSessionLocal() as session:
            async with session.begin():
                payload = await self.aggregate_metrics(
                    session, tenant_id, period_start, period_end
                )

                if fmt == "pdf":
                    content = self.generate_pdf_report(payload)
                else:
                    content = self.generate_json_report(payload)

                file_uri = self.store_report(
                    content, fmt, tenant_id, period_start, period_end
                )

                report = await self.create_report_record(
                    session,
                    tenant_id=tenant_id,
                    period_start=period_start,
                    period_end=period_end,
                    fmt=fmt,
                    file_uri=file_uri,
                    generated_at=payload.generated_at,
                )

        logger.info(
            json.dumps(
                {
                    "event": "compliance_report_generated",
                    "tenant_id": str(tenant_id),
                    "report_id": str(report.id),
                    "format": fmt,
                    "file_count": payload.file_count,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                }
            )
        )
        return report


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="fileguard.services.reports.generate_compliance_report",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def generate_compliance_report(
    self: Any,
    tenant_id: str,
    period_start: str,
    period_end: str,
    fmt: str = "json",
) -> dict[str, Any]:
    """Celery task: generate a compliance report for a single tenant/period.

    Parameters are passed as ISO-8601 strings so that they serialise cleanly
    over JSON.  :func:`asyncio.run` is used to drive the async service from
    the synchronous Celery worker.

    Args:
        tenant_id: Tenant UUID as a string.
        period_start: ISO-8601 timestamp for the period start.
        period_end: ISO-8601 timestamp for the period end.
        fmt: Output format — ``"json"`` (default) or ``"pdf"``.

    Returns:
        A dict with ``report_id`` and ``file_uri`` on success.

    Raises:
        :exc:`celery.exceptions.Retry`: On transient failure (up to 3 retries).
    """
    try:
        service = ReportService()
        tenant_uuid = uuid.UUID(tenant_id)
        start_dt = datetime.fromisoformat(period_start)
        end_dt = datetime.fromisoformat(period_end)

        report = asyncio.run(
            service.generate_and_store(tenant_uuid, start_dt, end_dt, fmt)
        )

        return {
            "report_id": str(report.id),
            "file_uri": report.file_uri,
        }

    except Exception as exc:
        logger.warning(
            "compliance_report_task_failed tenant_id=%s attempt=%d error=%s",
            tenant_id,
            self.request.retries + 1,
            exc,
        )
        raise self.retry(exc=exc)


@celery_app.task(
    name="fileguard.services.reports.generate_scheduled_reports",
)
def generate_scheduled_reports() -> dict[str, Any]:
    """Celery beat task: fan out report generation for all active tenants.

    Determines the most-recently-completed reporting period based on
    ``settings.REPORT_CADENCE`` (``"daily"`` or ``"weekly"``), queries all
    tenant IDs, and enqueues one :func:`generate_compliance_report` task per
    tenant for both JSON and PDF formats.

    Returns:
        A dict with ``tenants_processed`` count and the ``period`` covered.
    """
    now_utc = datetime.now(tz=timezone.utc)

    # Calculate the previous reporting period ---------------------------------
    if settings.REPORT_CADENCE == "weekly":
        # Previous Monday–Sunday week
        days_since_monday = now_utc.weekday()
        period_end = now_utc.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days_since_monday)
        period_start = period_end - timedelta(weeks=1)
    else:
        # Previous calendar day (UTC)
        period_end = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = period_end - timedelta(days=1)

    period_start_iso = period_start.isoformat()
    period_end_iso = period_end.isoformat()

    # Discover all tenants and enqueue tasks ----------------------------------
    tenant_ids = asyncio.run(_fetch_all_tenant_ids())

    dispatched = 0
    for tid in tenant_ids:
        for fmt in ("json", "pdf"):
            generate_compliance_report.delay(
                tenant_id=str(tid),
                period_start=period_start_iso,
                period_end=period_end_iso,
                fmt=fmt,
            )
        dispatched += 1

    logger.info(
        json.dumps(
            {
                "event": "scheduled_reports_dispatched",
                "tenants_processed": dispatched,
                "period_start": period_start_iso,
                "period_end": period_end_iso,
                "cadence": settings.REPORT_CADENCE,
            }
        )
    )
    return {
        "tenants_processed": dispatched,
        "period": {"start": period_start_iso, "end": period_end_iso},
    }


async def _fetch_all_tenant_ids() -> list[uuid.UUID]:
    """Return the list of all tenant UUIDs from the database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TenantConfig.id))
        return list(result.scalars().all())
