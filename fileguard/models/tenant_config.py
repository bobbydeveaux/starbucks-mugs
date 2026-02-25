import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base


class TenantConfig(Base):
    """Per-tenant configuration: auth, disposition rules, and integration settings."""

    __tablename__ = "tenant_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    disposition_rules: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    custom_patterns: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    siem_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
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
