import uuid

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fileguard.db.session import Base


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
