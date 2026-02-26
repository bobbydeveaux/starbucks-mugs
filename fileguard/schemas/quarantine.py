"""Pydantic schemas for the quarantine lifecycle API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import UUID4, BaseModel, Field


class QuarantinedFileResponse(BaseModel):
    """Read schema for a quarantined file record."""

    model_config = {"from_attributes": True}

    id: UUID4
    tenant_id: UUID4
    scan_event_id: UUID4 | None = None
    file_hash: str
    file_name: str
    file_size_bytes: int
    mime_type: str
    reason: Literal["av_threat", "pii", "policy"]
    status: Literal["active", "expired", "released", "deleted"]
    ttl_seconds: int
    expires_at: datetime
    created_at: datetime
    released_at: datetime | None = None


class QuarantineRequest(BaseModel):
    """Input schema for explicitly quarantining a file via the API."""

    tenant_id: UUID4
    file_hash: str = Field(..., description="SHA-256 hex digest of the file")
    file_name: str = Field(..., max_length=1024)
    file_size_bytes: int = Field(..., ge=0)
    mime_type: str
    reason: Literal["av_threat", "pii", "policy"] = "av_threat"
    scan_event_id: UUID4 | None = None
    ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        description="TTL in seconds. Defaults to QUARANTINE_DEFAULT_TTL_SECONDS.",
    )


class ReleaseRequest(BaseModel):
    """Request body for releasing a quarantined file."""

    quarantine_id: UUID4


class QuarantineListResponse(BaseModel):
    """Paginated list of quarantine records."""

    items: list[QuarantinedFileResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
