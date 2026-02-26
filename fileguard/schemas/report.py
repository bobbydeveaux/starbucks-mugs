"""Pydantic schemas for compliance report data structures.

These schemas define the validated data structures used when generating,
storing, and reading compliance reports.  ``ReportPayload`` is the canonical
in-memory representation of an aggregated report, while
``ComplianceReportCreate`` / ``ComplianceReportRead`` mirror the
``compliance_report`` database table.

Usage::

    from fileguard.schemas.report import ReportPayload, VerdictBreakdown

    payload = ReportPayload(
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
        generated_at=now,
        file_count=42,
        verdict_breakdown=VerdictBreakdown(clean=40, flagged=1, rejected=1),
        pii_hits_by_category={"NI_NUMBER": 3, "EMAIL": 12},
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import UUID4, BaseModel, Field, field_validator


class VerdictBreakdown(BaseModel):
    """Counts of scan events by verdict (outcome) for a report period.

    Attributes:
        clean: Number of scan events with status ``"clean"``.
        flagged: Number of scan events with status ``"flagged"`` (PII or
            low-severity AV hit that did not result in a block).
        rejected: Number of scan events with status ``"rejected"`` (blocked
            by AV or disposition rules).
    """

    clean: int = Field(default=0, ge=0, description="Count of clean scan events")
    flagged: int = Field(default=0, ge=0, description="Count of flagged scan events")
    rejected: int = Field(default=0, ge=0, description="Count of rejected scan events")

    @property
    def total(self) -> int:
        """Total event count across all verdicts."""
        return self.clean + self.flagged + self.rejected


class ReportPayload(BaseModel):
    """Full aggregated data payload for a generated compliance report.

    This is the canonical in-memory representation that the report service
    populates after querying ``scan_event`` records for the given period.
    It is serialised to either JSON bytes or a PDF document before storage.

    Attributes:
        tenant_id: UUID of the tenant this report covers.
        period_start: Start of the report period (inclusive), timezone-aware.
        period_end: End of the report period (exclusive), timezone-aware.
        generated_at: Timestamp when the report was generated (UTC).
        file_count: Total number of file scans recorded in the period.
        verdict_breakdown: Per-verdict event counts.
        pii_hits_by_category: Mapping of PII category name (e.g.
            ``"NI_NUMBER"``, ``"EMAIL"``) to the number of scan events that
            contained at least one finding of that category.
        top_file_types: Mapping of MIME type to scan count, sorted by
            frequency (up to 10 entries).
        average_scan_duration_ms: Mean scan processing time in milliseconds
            across all events in the period.
    """

    tenant_id: UUID4
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    file_count: int = Field(ge=0, description="Total file scans in the period")
    verdict_breakdown: VerdictBreakdown
    pii_hits_by_category: dict[str, int] = Field(
        default_factory=dict,
        description="PII category → hit count mapping",
    )
    top_file_types: dict[str, int] = Field(
        default_factory=dict,
        description="MIME type → scan count (up to 10 entries)",
    )
    average_scan_duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Mean scan duration in milliseconds",
    )

    @field_validator("period_end")
    @classmethod
    def period_end_after_start(cls, v: datetime, info: object) -> datetime:
        """Ensure period_end is strictly after period_start."""
        # Access the already-validated period_start from the field data
        data = getattr(info, "data", {})
        period_start = data.get("period_start")
        if period_start is not None and v <= period_start:
            raise ValueError("period_end must be after period_start")
        return v


class ComplianceReportCreate(BaseModel):
    """Input schema for triggering compliance report generation.

    Attributes:
        tenant_id: The tenant for whom to generate the report.
        period_start: Report period start (inclusive), must be timezone-aware.
        period_end: Report period end (exclusive), must be timezone-aware.
        format: Output format — ``"json"`` (default) or ``"pdf"``.
    """

    tenant_id: UUID4
    period_start: datetime
    period_end: datetime
    format: Literal["json", "pdf"] = "json"

    @field_validator("period_end")
    @classmethod
    def period_end_after_start(cls, v: datetime, info: object) -> datetime:
        data = getattr(info, "data", {})
        period_start = data.get("period_start")
        if period_start is not None and v <= period_start:
            raise ValueError("period_end must be after period_start")
        return v


class ComplianceReportRead(BaseModel):
    """Read schema for a ``compliance_report`` database row.

    Returned by API endpoints that list or look up existing reports.
    """

    model_config = {"from_attributes": True}

    id: UUID4
    tenant_id: UUID4
    period_start: datetime
    period_end: datetime
    format: str
    file_uri: str
    generated_at: datetime
