"""Pydantic schemas for compliance report API responses.

These schemas are used by the reports API handlers to serialise
ComplianceReport ORM model instances into JSON-compatible response bodies.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import UUID4, BaseModel


class ReportSummary(BaseModel):
    """Metadata for a single compliance report returned in list and download responses."""

    model_config = {"from_attributes": True}

    id: UUID4
    tenant_id: UUID4
    period_start: datetime
    period_end: datetime
    format: str
    file_uri: str
    generated_at: datetime


class ReportListResponse(BaseModel):
    """Paginated list of compliance report summaries."""

    items: list[ReportSummary]
    total: int
    page: int
    page_size: int
