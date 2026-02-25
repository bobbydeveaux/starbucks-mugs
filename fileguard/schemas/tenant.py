"""Pydantic schemas for tenant configuration.

TenantConfig is the canonical in-memory representation of a tenant record.
The auth middleware populates ``request.state.tenant`` with a validated
TenantConfig instance after a successful authentication check.
"""

import uuid
from typing import Any

from pydantic import UUID4, BaseModel, Field, HttpUrl, field_validator


class TenantConfig(BaseModel):
    """Serialisable tenant configuration attached to authenticated requests.

    A tenant may authenticate using either an API key (compared via bcrypt)
    or an OAuth 2.0 JWT (verified against a JWKS endpoint).  At least one
    of (``api_key_hash``, ``jwks_url`` + ``client_id``) must be populated for
    authentication to succeed.

    Attributes:
        id: Unique tenant identifier (UUID).
        api_key_hash: bcrypt hash of the tenant's raw API key.  ``None`` when
            the tenant authenticates exclusively via OAuth 2.0.
        jwks_url: URL of the tenant's JWKS endpoint used to verify JWT
            signatures.  ``None`` when API-key-only authentication is used.
        client_id: OAuth 2.0 ``client_id`` / ``aud`` claim expected in JWTs.
            ``None`` when API-key-only authentication is used.
        rate_limit_rpm: Per-tenant request rate limit in requests per minute.
            Defaults to 100.
        disposition_rules: Optional per-file-type disposition overrides
            (block | quarantine | pass-with-flags).
        custom_patterns: Optional user-defined regex patterns for PII detection.
        webhook_url: Optional URL to deliver async scan result callbacks.
        siem_config: Optional SIEM integration configuration.
    """

    model_config = {"from_attributes": True}

    id: UUID4
    api_key_hash: str | None = None
    jwks_url: HttpUrl | None = None
    client_id: str | None = None
    rate_limit_rpm: int = Field(default=100, ge=0)
    disposition_rules: dict[str, Any] | None = None
    custom_patterns: dict[str, Any] | None = None
    webhook_url: str | None = None
    siem_config: dict[str, Any] | None = None

    @field_validator("rate_limit_rpm")
    @classmethod
    def rate_limit_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("rate_limit_rpm must be >= 0")
        return v
