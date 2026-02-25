import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base

ReportFormat = Enum("pdf", "json", name="report_format")


class ComplianceReport(Base):
    """Metadata record for a generated compliance report file."""

    __tablename__ = "compliance_report"
    __table_args__ = (
        Index("ix_compliance_report_tenant_id", "tenant_id"),
        Index("ix_compliance_report_period", "period_start", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_config.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    format: Mapped[str] = mapped_column(ReportFormat, nullable=False)
    file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationship
    tenant: Mapped["TenantConfig"] = relationship(  # noqa: F821
        "TenantConfig", back_populates="compliance_reports"
    )
