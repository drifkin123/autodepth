"""raw page archive and crawl target pipeline

Revision ID: 0003_raw_page_pipeline
Revises: 0002_scraper_observability
Create Date: 2026-04-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_raw_page_pipeline"
down_revision: str | None = "0002_scraper_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crawl_targets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("request_method", sa.Text(), nullable=False, server_default="GET"),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("discovered_from_raw_page_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "request_fingerprint",
            name="uq_crawl_targets_request_fingerprint",
        ),
    )
    op.create_index(
        "ix_crawl_targets_source_state_priority",
        "crawl_targets",
        ["source", "state", "priority"],
    )
    op.create_index("ix_crawl_targets_next_fetch_at", "crawl_targets", ["next_fetch_at"])
    op.create_index("ix_crawl_targets_type_state", "crawl_targets", ["target_type", "state"])

    op.create_table(
        "raw_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column(
            "crawl_target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_targets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "response_headers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetch_error", sa.Text(), nullable=True),
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
    op.create_index("ix_raw_pages_source_fetched_at", "raw_pages", ["source", "fetched_at"])
    op.create_index("ix_raw_pages_target_type", "raw_pages", ["target_type"])
    op.create_index("ix_raw_pages_status_code", "raw_pages", ["status_code"])
    op.create_index("ix_raw_pages_content_sha256", "raw_pages", ["content_sha256"])

    op.create_table(
        "raw_parse_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "raw_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parser_name", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("records_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("targets_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_raw_parse_runs_page_created",
        "raw_parse_runs",
        ["raw_page_id", "created_at"],
    )
    op.create_index(
        "ix_raw_parse_runs_parser_version",
        "raw_parse_runs",
        ["parser_name", "parser_version"],
    )
    op.create_index("ix_raw_parse_runs_status", "raw_parse_runs", ["status"])

    op.create_table(
        "raw_page_lots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "raw_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "auction_lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auction_lots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "raw_page_id",
            "auction_lot_id",
            "relationship_type",
            name="uq_raw_page_lots_page_lot_type",
        ),
    )
    op.create_index("ix_raw_page_lots_lot_id", "raw_page_lots", ["auction_lot_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_page_lots_lot_id", table_name="raw_page_lots")
    op.drop_table("raw_page_lots")
    op.drop_index("ix_raw_parse_runs_status", table_name="raw_parse_runs")
    op.drop_index("ix_raw_parse_runs_parser_version", table_name="raw_parse_runs")
    op.drop_index("ix_raw_parse_runs_page_created", table_name="raw_parse_runs")
    op.drop_table("raw_parse_runs")
    op.drop_index("ix_raw_pages_content_sha256", table_name="raw_pages")
    op.drop_index("ix_raw_pages_status_code", table_name="raw_pages")
    op.drop_index("ix_raw_pages_target_type", table_name="raw_pages")
    op.drop_index("ix_raw_pages_source_fetched_at", table_name="raw_pages")
    op.drop_table("raw_pages")
    op.drop_index("ix_crawl_targets_type_state", table_name="crawl_targets")
    op.drop_index("ix_crawl_targets_next_fetch_at", table_name="crawl_targets")
    op.drop_index("ix_crawl_targets_source_state_priority", table_name="crawl_targets")
    op.drop_table("crawl_targets")
