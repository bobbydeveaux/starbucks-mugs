"""Pydantic schemas for tenant configuration."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class DispositionRule(BaseModel):
    """Per file-type disposition rule."""

    action: str = Field(
        ...,
        pattern="^(block|quarantine|pass-with-flags)$",
        description="Disposition action: block, quarantine, or pass-with-flags",
    )
    mime_types: list[str] = Field(
        default_factory=list,
        description="MIME types this rule applies to; empty means all types",
    )


class SiemConfig(BaseModel):
    """SIEM integration configuration."""

    type: str = Field(..., description="SIEM type: splunk or watchtower")
    endpoint: str = Field(..., description="SIEM endpoint URL or HEC URL")
    credentials_ref: str = Field(
        ...,
        description="Reference to credentials secret (e.g. env var name or Vault path)",
    )


class TenantConfig(BaseModel):
    """Pydantic model representing a tenant's configuration.

    This schema is populated from the database at request time and attached to
    ``request.state.tenant`` by the authentication middleware.
    """

    id: uuid.UUID = Field(..., description="Tenant unique identifier")
    api_key_hash: str | None = Field(
        None,
        description="bcrypt-hashed API key; present when API key auth is configured",
    )

    # OAuth 2.0 client credentials configuration
    jwks_url: HttpUrl | None = Field(
        None,
        description="JWKS endpoint URL for JWT signature verification (OAuth 2.0)",
    )
    client_id: str | None = Field(
        None,
        description="OAuth 2.0 client ID; validated against the JWT 'sub' or 'client_id' claim",
    )
    audience: str | None = Field(
        None,
        description="Expected JWT audience claim value",
    )

    # Rate limiting
    rate_limit_rpm: int = Field(
        default=100,
        ge=1,
        le=100_000,
        description="Maximum requests per minute for this tenant; defaults to 100",
    )

    # Disposition and detection configuration
    disposition_rules: list[DispositionRule] = Field(
        default_factory=list,
        description="Per file-type disposition rules; evaluated in order",
    )
    custom_patterns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Custom regex PII pattern definitions loaded at startup",
    )

    # Webhook and SIEM
    webhook_url: str | None = Field(
        None,
        description="Tenant-configured webhook URL for scan completion callbacks",
    )
    siem_config: SiemConfig | None = Field(
        None,
        description="SIEM forwarding configuration; None disables forwarding for this tenant",
    )

    @field_validator("api_key_hash", "jwks_url", "client_id", mode="before")
    @classmethod
    def at_least_one_auth_method(cls, v: Any, info: Any) -> Any:
        # Individual field validation; cross-field check is done at model level
        return v

    def has_api_key_auth(self) -> bool:
        """Return True if API key authentication is configured."""
        return self.api_key_hash is not None

    def has_oauth_auth(self) -> bool:
        """Return True if OAuth 2.0 authentication is configured."""
        return self.jwks_url is not None and self.client_id is not None

    model_config = {"frozen": True}
