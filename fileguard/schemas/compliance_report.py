"""Pydantic schemas for compliance report API responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ComplianceReportOut(BaseModel):
    """Serialisable representation of a compliance report metadata record.

    Attributes:
        id: Unique report identifier (UUID).
        tenant_id: Owning tenant UUID.
        period_start: UTC timestamp for the start of the reporting period.
        period_end: UTC timestamp for the end of the reporting period.
        format: Report format — ``"pdf"`` or ``"json"``.
        file_uri: Location of the generated report file (cloud storage URI or
            HTTPS URL).
        generated_at: UTC timestamp when the report was generated.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    tenant_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    format: str
    file_uri: str
    generated_at: datetime


class ComplianceReportListResponse(BaseModel):
    """Paginated list of compliance report metadata records.

    Attributes:
        reports: Page of report records.
        total: Total number of matching reports across all pages.
        limit: Page size requested.
        offset: Zero-based offset of the first returned record.
    """

    reports: list[ComplianceReportOut]
    total: int
    limit: int
    offset: int
