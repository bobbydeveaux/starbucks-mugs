import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base

BucketType = Enum("s3", "gcs", name="batch_bucket_type")
BatchJobStatus = Enum("idle", "running", "completed", "failed", name="batch_job_status")


class BatchJob(Base):
    """Scheduled cloud-bucket scan job configuration and execution state."""

    __tablename__ = "batch_job"
    __table_args__ = (Index("ix_batch_job_tenant_id", "tenant_id"),)

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
    bucket_type: Mapped[str] = mapped_column(BucketType, nullable=False)
    bucket_name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_schedule: Mapped[str] = mapped_column(Text, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        BatchJobStatus, nullable=False, server_default="idle"
    )
    result_manifest_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationship
    tenant: Mapped["TenantConfig"] = relationship(  # noqa: F821
        "TenantConfig", back_populates="batch_jobs"
    )
