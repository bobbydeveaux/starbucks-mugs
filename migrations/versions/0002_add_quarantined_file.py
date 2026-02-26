"""Add quarantined_file table with quarantine_status and quarantine_reason enums.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Custom ENUM types ---
    op.execute(
        "CREATE TYPE quarantine_status AS ENUM ('active', 'expired', 'released', 'deleted')"
    )
    op.execute(
        "CREATE TYPE quarantine_reason AS ENUM ('av_threat', 'pii', 'policy')"
    )

    quarantine_status = postgresql.ENUM(
        "active", "expired", "released", "deleted",
        name="quarantine_status",
        create_type=False,
    )
    quarantine_reason = postgresql.ENUM(
        "av_threat", "pii", "policy",
        name="quarantine_reason",
        create_type=False,
    )

    # --- quarantined_file ---
    op.create_table(
        "quarantined_file",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenant_config.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scan_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scan_event.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("reason", quarantine_reason, nullable=False),
        sa.Column(
            "status",
            quarantine_status,
            nullable=False,
            server_default="active",
        ),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_quarantined_file_tenant_id", "quarantined_file", ["tenant_id"])
    op.create_index("ix_quarantined_file_scan_event_id", "quarantined_file", ["scan_event_id"])
    op.create_index("ix_quarantined_file_file_hash", "quarantined_file", ["file_hash"])
    op.create_index(
        "ix_quarantined_file_expires_at",
        "quarantined_file",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_quarantined_file_expires_at", table_name="quarantined_file")
    op.drop_index("ix_quarantined_file_file_hash", table_name="quarantined_file")
    op.drop_index("ix_quarantined_file_scan_event_id", table_name="quarantined_file")
    op.drop_index("ix_quarantined_file_tenant_id", table_name="quarantined_file")
    op.drop_table("quarantined_file")

    op.execute("DROP TYPE IF EXISTS quarantine_reason")
    op.execute("DROP TYPE IF EXISTS quarantine_status")
