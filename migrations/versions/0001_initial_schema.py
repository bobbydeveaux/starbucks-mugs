"""Initial schema: tenant_config, scan_event, batch_job, compliance_report

Revision ID: 0001
Revises:
Create Date: 2026-02-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Custom ENUM types ---
    scan_status = postgresql.ENUM(
        "clean", "flagged", "rejected", name="scan_status", create_type=False
    )
    scan_action = postgresql.ENUM(
        "pass", "quarantine", "block", name="scan_action", create_type=False
    )
    batch_bucket_type = postgresql.ENUM(
        "s3", "gcs", name="batch_bucket_type", create_type=False
    )
    batch_job_status = postgresql.ENUM(
        "idle", "running", "completed", "failed",
        name="batch_job_status", create_type=False
    )
    report_format = postgresql.ENUM(
        "pdf", "json", name="report_format", create_type=False
    )

    op.execute("CREATE TYPE scan_status AS ENUM ('clean', 'flagged', 'rejected')")
    op.execute("CREATE TYPE scan_action AS ENUM ('pass', 'quarantine', 'block')")
    op.execute("CREATE TYPE batch_bucket_type AS ENUM ('s3', 'gcs')")
    op.execute(
        "CREATE TYPE batch_job_status AS ENUM ('idle', 'running', 'completed', 'failed')"
    )
    op.execute("CREATE TYPE report_format AS ENUM ('pdf', 'json')")

    # --- tenant_config ---
    op.create_table(
        "tenant_config",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column(
            "disposition_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "custom_patterns",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("siem_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "rate_limit_rpm", sa.Integer(), nullable=False, server_default="100"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- scan_event ---
    op.create_table(
        "scan_event",
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
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            scan_status,
            nullable=False,
        ),
        sa.Column(
            "action_taken",
            scan_action,
            nullable=False,
        ),
        sa.Column(
            "findings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("scan_duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("hmac_signature", sa.Text(), nullable=False),
    )
    op.create_index("ix_scan_event_tenant_id", "scan_event", ["tenant_id"])
    op.create_index("ix_scan_event_created_at", "scan_event", ["created_at"])
    op.create_index("ix_scan_event_file_hash", "scan_event", ["file_hash"])

    # Append-only trigger: prevent UPDATE and DELETE on scan_event
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_scan_event_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'scan_event is append-only: UPDATE is not permitted';
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'scan_event is append-only: DELETE is not permitted';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tg_scan_event_append_only
        BEFORE UPDATE OR DELETE ON scan_event
        FOR EACH ROW EXECUTE FUNCTION fn_scan_event_append_only()
        """
    )

    # --- batch_job ---
    op.create_table(
        "batch_job",
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
            "bucket_type",
            batch_bucket_type,
            nullable=False,
        ),
        sa.Column("bucket_name", sa.Text(), nullable=False),
        sa.Column("prefix_filter", sa.Text(), nullable=True),
        sa.Column("cron_schedule", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            batch_job_status,
            nullable=False,
            server_default="idle",
        ),
        sa.Column("result_manifest_uri", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_batch_job_tenant_id", "batch_job", ["tenant_id"])

    # --- compliance_report ---
    op.create_table(
        "compliance_report",
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
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "format",
            report_format,
            nullable=False,
        ),
        sa.Column("file_uri", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_compliance_report_tenant_id", "compliance_report", ["tenant_id"]
    )
    op.create_index(
        "ix_compliance_report_period",
        "compliance_report",
        ["period_start", "period_end"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_index("ix_compliance_report_period", table_name="compliance_report")
    op.drop_index("ix_compliance_report_tenant_id", table_name="compliance_report")
    op.drop_table("compliance_report")

    op.drop_index("ix_batch_job_tenant_id", table_name="batch_job")
    op.drop_table("batch_job")

    # Drop trigger and function before dropping scan_event
    op.execute("DROP TRIGGER IF EXISTS tg_scan_event_append_only ON scan_event")
    op.execute("DROP FUNCTION IF EXISTS fn_scan_event_append_only()")

    op.drop_index("ix_scan_event_file_hash", table_name="scan_event")
    op.drop_index("ix_scan_event_created_at", table_name="scan_event")
    op.drop_index("ix_scan_event_tenant_id", table_name="scan_event")
    op.drop_table("scan_event")

    op.drop_table("tenant_config")

    # Drop custom ENUM types
    op.execute("DROP TYPE IF EXISTS report_format")
    op.execute("DROP TYPE IF EXISTS batch_job_status")
    op.execute("DROP TYPE IF EXISTS batch_bucket_type")
    op.execute("DROP TYPE IF EXISTS scan_action")
    op.execute("DROP TYPE IF EXISTS scan_status")
