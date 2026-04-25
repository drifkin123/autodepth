"""initial raw auction ingestion schema

Revision ID: 0001_raw_auction_ingestion
Revises:
Create Date: 2026-04-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_raw_auction_ingestion"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "auction_lots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_auction_id", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("auction_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("sold_price", sa.Integer(), nullable=True),
        sa.Column("high_bid", sa.Integer(), nullable=True),
        sa.Column("bid_count", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default="USD"),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("make", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("trim", sa.Text(), nullable=True),
        sa.Column("vin", sa.Text(), nullable=True),
        sa.Column("mileage", sa.Integer(), nullable=True),
        sa.Column("exterior_color", sa.Text(), nullable=True),
        sa.Column("interior_color", sa.Text(), nullable=True),
        sa.Column("transmission", sa.Text(), nullable=True),
        sa.Column("drivetrain", sa.Text(), nullable=True),
        sa.Column("engine", sa.Text(), nullable=True),
        sa.Column("body_style", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("seller", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("raw_summary", sa.Text(), nullable=True),
        sa.Column(
            "vehicle_details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "list_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "detail_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("detail_html", sa.Text(), nullable=True),
        sa.Column("detail_scraped_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("source", "source_auction_id", name="uq_auction_lots_source_id"),
        sa.UniqueConstraint("source", "canonical_url", name="uq_auction_lots_source_url"),
    )
    op.create_index("ix_auction_lots_source_status", "auction_lots", ["source", "auction_status"])
    op.create_index("ix_auction_lots_source_ended_at", "auction_lots", ["source", "ended_at"])
    op.create_index("ix_auction_lots_make_model_year", "auction_lots", ["make", "model", "year"])
    op.create_index("ix_auction_lots_ended_at", "auction_lots", ["ended_at"])

    op.create_table(
        "auction_images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "auction_lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auction_lots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "source_payload",
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
    op.create_index("ix_auction_images_auction_lot_id", "auction_images", ["auction_lot_id"])
    op.create_index("ix_auction_images_source_image_url", "auction_images", ["source", "image_url"])

    op.create_table(
        "scrape_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default="incremental"),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_scrape_runs_source_started_at", "scrape_runs", ["source", "started_at"])
    op.create_index("ix_scrape_runs_status", "scrape_runs", ["status"])

    op.create_table(
        "crawl_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source", "mode", name="uq_crawl_state_source_mode"),
    )
    op.create_index("ix_crawl_state_source_mode", "crawl_state", ["source", "mode"])


def downgrade() -> None:
    op.drop_index("ix_crawl_state_source_mode", table_name="crawl_state")
    op.drop_table("crawl_state")
    op.drop_index("ix_scrape_runs_status", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_source_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")
    op.drop_index("ix_auction_images_source_image_url", table_name="auction_images")
    op.drop_index("ix_auction_images_auction_lot_id", table_name="auction_images")
    op.drop_table("auction_images")
    op.drop_index("ix_auction_lots_ended_at", table_name="auction_lots")
    op.drop_index("ix_auction_lots_make_model_year", table_name="auction_lots")
    op.drop_index("ix_auction_lots_source_ended_at", table_name="auction_lots")
    op.drop_index("ix_auction_lots_source_status", table_name="auction_lots")
    op.drop_table("auction_lots")
