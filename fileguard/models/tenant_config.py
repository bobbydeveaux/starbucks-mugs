import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base


class TenantConfig(Base):
    """ORM model for per-tenant configuration.

    Stores authentication credentials (API key hash or OAuth 2.0 parameters)
    and per-tenant policy settings loaded by the auth middleware at request time.
    """

    __tablename__ = "tenant_config"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_tenant_config_client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # API key authentication: bcrypt hash of the raw API key
    api_key_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OAuth 2.0 authentication
    jwks_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Per-tenant rate limit (requests per minute); 0 means inherit global default
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Policy configuration (used by downstream pipeline components)
    disposition_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    custom_patterns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    siem_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    scan_events: Mapped[list["ScanEvent"]] = relationship(  # noqa: F821
        "ScanEvent", back_populates="tenant", cascade="all, delete-orphan"
    )
    batch_jobs: Mapped[list["BatchJob"]] = relationship(  # noqa: F821
        "BatchJob", back_populates="tenant", cascade="all, delete-orphan"
    )
    compliance_reports: Mapped[list["ComplianceReport"]] = relationship(  # noqa: F821
        "ComplianceReport", back_populates="tenant", cascade="all, delete-orphan"
    )
