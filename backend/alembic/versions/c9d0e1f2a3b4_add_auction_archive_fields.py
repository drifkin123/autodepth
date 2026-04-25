"""add auction archive fields

Revision ID: c9d0e1f2a3b4
Revises: f7e8d9c0b1a2
Create Date: 2026-04-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "f7e8d9c0b1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicle_sales", sa.Column("source_auction_id", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("auction_status", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("high_bid", sa.Integer(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("bid_count", sa.Integer(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("subtitle", sa.Text(), nullable=True))
    op.add_column(
        "vehicle_sales",
        sa.Column("detail_scraped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vehicle_sales",
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vehicle_sales",
        sa.Column(
            "vehicle_details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_index(
        "ix_vehicle_sales_source_auction_id",
        "vehicle_sales",
        ["source", "source_auction_id"],
    )
    op.create_index(
        "ix_vehicle_sales_source_auction_status",
        "vehicle_sales",
        ["source", "auction_status"],
    )
    op.create_index(
        "ix_vehicle_sales_make_model_year",
        "vehicle_sales",
        ["make", "model", "year"],
    )
    op.create_index("ix_vehicle_sales_sold_at", "vehicle_sales", ["sold_at"])

    op.create_table(
        "auction_images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("vehicle_sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_auction_images_vehicle_sale_id", "auction_images", ["vehicle_sale_id"])
    op.create_index("ix_auction_images_source_url", "auction_images", ["source_url"])

    op.create_table(
        "crawl_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("crawl_mode", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auction_ids_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_crawl_state_source_mode", "crawl_state", ["source", "crawl_mode"])


def downgrade() -> None:
    op.drop_index("ix_crawl_state_source_mode", table_name="crawl_state")
    op.drop_table("crawl_state")
    op.drop_index("ix_auction_images_source_url", table_name="auction_images")
    op.drop_index("ix_auction_images_vehicle_sale_id", table_name="auction_images")
    op.drop_table("auction_images")
    op.drop_index("ix_vehicle_sales_sold_at", table_name="vehicle_sales")
    op.drop_index("ix_vehicle_sales_make_model_year", table_name="vehicle_sales")
    op.drop_index("ix_vehicle_sales_source_auction_status", table_name="vehicle_sales")
    op.drop_index("ix_vehicle_sales_source_auction_id", table_name="vehicle_sales")
    op.drop_column("vehicle_sales", "vehicle_details")
    op.drop_column("vehicle_sales", "image_count")
    op.drop_column("vehicle_sales", "detail_scraped_at")
    op.drop_column("vehicle_sales", "subtitle")
    op.drop_column("vehicle_sales", "title")
    op.drop_column("vehicle_sales", "bid_count")
    op.drop_column("vehicle_sales", "high_bid")
    op.drop_column("vehicle_sales", "auction_status")
    op.drop_column("vehicle_sales", "source_auction_id")
