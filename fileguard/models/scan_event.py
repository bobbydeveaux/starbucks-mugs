import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, Text, event, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base

ScanStatus = Enum("clean", "flagged", "rejected", name="scan_status")
ScanAction = Enum("pass", "quarantine", "block", name="scan_action")


class ScanEvent(Base):
    """Tamper-evident audit record of a single file scan.

    Append-only: no UPDATE or DELETE is permitted at the application layer.
    A PostgreSQL trigger (defined in the migration) enforces this at the DB level.
    """

    __tablename__ = "scan_event"
    __table_args__ = (
        Index("ix_scan_event_tenant_id", "tenant_id"),
        Index("ix_scan_event_created_at", "created_at"),
        Index("ix_scan_event_file_hash", "file_hash"),
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
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(ScanStatus, nullable=False)
    action_taken: Mapped[str] = mapped_column(ScanAction, nullable=False)
    findings: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    scan_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    hmac_signature: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationship
    tenant: Mapped["TenantConfig"] = relationship(  # noqa: F821
        "TenantConfig", back_populates="scan_events"
    )


def _raise_on_update(mapper, connection, target):
    """Prevent in-process UPDATE on ScanEvent (append-only guard)."""
    raise RuntimeError(
        "ScanEvent is append-only; UPDATE operations are not permitted."
    )


def _raise_on_delete(mapper, connection, target):
    """Prevent in-process DELETE on ScanEvent (append-only guard)."""
    raise RuntimeError(
        "ScanEvent is append-only; DELETE operations are not permitted."
    )


event.listen(ScanEvent, "before_update", _raise_on_update)
event.listen(ScanEvent, "before_delete", _raise_on_delete)
