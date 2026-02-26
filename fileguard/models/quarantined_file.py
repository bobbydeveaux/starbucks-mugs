"""QuarantinedFile ORM model.

Tracks metadata for files that have been isolated by the QuarantineService.
The encrypted file bytes are stored in Redis (keyed by ``id``) with an
automatic TTL; this table provides a durable, queryable record of every
quarantine action and its current lifecycle state.

Lifecycle states
----------------
``active``
    File is encrypted and accessible in Redis; TTL has not yet expired.
``expired``
    Redis TTL elapsed; the encrypted blob is gone.  The metadata row is
    retained for compliance and audit purposes.
``released``
    An operator explicitly released the file (e.g. false-positive review).
    ``released_at`` records when the release occurred.
``deleted``
    Operator manually deleted the record and purged it from Redis before TTL.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fileguard.db.base import Base

QuarantineStatus = Enum(
    "active", "expired", "released", "deleted",
    name="quarantine_status",
)

QuarantineReason = Enum(
    "av_threat", "pii", "policy",
    name="quarantine_reason",
)


class QuarantinedFile(Base):
    """Metadata record for a quarantined file.

    The encrypted payload lives in Redis under the key
    ``fileguard:quarantine:{id}`` with a TTL set to ``ttl_seconds``.
    This row is the durable, queryable counterpart that survives Redis
    eviction.
    """

    __tablename__ = "quarantined_file"

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
        index=True,
    )
    # Optional link to the scan that triggered quarantine.
    scan_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scan_event.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    file_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)

    reason: Mapped[str] = mapped_column(QuarantineReason, nullable=False)
    status: Mapped[str] = mapped_column(
        QuarantineStatus,
        nullable=False,
        server_default="active",
    )

    # TTL in seconds recorded at quarantine time (informational; Redis enforces it).
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # Computed expiry timestamp stored for efficient range queries.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Populated when status transitions to 'released'.
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tenant: Mapped["TenantConfig"] = relationship(  # noqa: F821
        "TenantConfig", back_populates="quarantined_files"
    )
    scan_event: Mapped["ScanEvent | None"] = relationship(  # noqa: F821
        "ScanEvent",
        foreign_keys=[scan_event_id],
    )
