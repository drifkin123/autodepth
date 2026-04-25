"""scraper observability tables

Revision ID: 0002_scraper_observability
Revises: 0001_raw_auction_ingestion
Create Date: 2026-04-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_scraper_observability"
down_revision: str | None = "0001_raw_auction_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_request_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scrape_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_delay_seconds", sa.Float(), nullable=True),
        sa.Column("raw_item_count", sa.Integer(), nullable=True),
        sa.Column("parsed_lot_count", sa.Integer(), nullable=True),
        sa.Column(
            "skip_counts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_scrape_request_logs_run_created",
        "scrape_request_logs",
        ["scrape_run_id", "created_at"],
    )
    op.create_index(
        "ix_scrape_request_logs_source_created",
        "scrape_request_logs",
        ["source", "created_at"],
    )
    op.create_index("ix_scrape_request_logs_outcome", "scrape_request_logs", ["outcome"])
    op.create_index(
        "ix_scrape_request_logs_status_code",
        "scrape_request_logs",
        ["status_code"],
    )

    op.create_table(
        "scrape_anomalies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scrape_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_scrape_anomalies_run_created",
        "scrape_anomalies",
        ["scrape_run_id", "created_at"],
    )
    op.create_index(
        "ix_scrape_anomalies_source_created",
        "scrape_anomalies",
        ["source", "created_at"],
    )
    op.create_index("ix_scrape_anomalies_severity", "scrape_anomalies", ["severity"])
    op.create_index("ix_scrape_anomalies_code", "scrape_anomalies", ["code"])


def downgrade() -> None:
    op.drop_index("ix_scrape_anomalies_code", table_name="scrape_anomalies")
    op.drop_index("ix_scrape_anomalies_severity", table_name="scrape_anomalies")
    op.drop_index("ix_scrape_anomalies_source_created", table_name="scrape_anomalies")
    op.drop_index("ix_scrape_anomalies_run_created", table_name="scrape_anomalies")
    op.drop_table("scrape_anomalies")
    op.drop_index("ix_scrape_request_logs_status_code", table_name="scrape_request_logs")
    op.drop_index("ix_scrape_request_logs_outcome", table_name="scrape_request_logs")
    op.drop_index("ix_scrape_request_logs_source_created", table_name="scrape_request_logs")
    op.drop_index("ix_scrape_request_logs_run_created", table_name="scrape_request_logs")
    op.drop_table("scrape_request_logs")
