"""initial schema

Revision ID: b63cfeaadd05
Revises:
Create Date: 2026-03-28

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b63cfeaadd05"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable TimescaleDB extension
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # ── cars ──────────────────────────────────────────────────────────────────
    op.create_table(
        "cars",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("make", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("trim", sa.Text, nullable=False),
        sa.Column("year_start", sa.Integer, nullable=False),
        sa.Column("year_end", sa.Integer, nullable=True),
        sa.Column("production_count", sa.Integer, nullable=True),
        sa.Column("engine", sa.Text, nullable=False),
        sa.Column("is_naturally_aspirated", sa.Boolean, nullable=False),
        sa.Column("msrp_original", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ── vehicle_sales (TimescaleDB hypertable partitioned on listed_at) ───────
    op.create_table(
        "vehicle_sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "car_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cars.id"),
            nullable=False,
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False, unique=True),
        sa.Column("sale_type", sa.Text, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("mileage", sa.Integer, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("asking_price", sa.Integer, nullable=False),
        sa.Column("sold_price", sa.Integer, nullable=True),
        sa.Column("is_sold", sa.Boolean, nullable=False),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("condition_notes", sa.Text, nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_vehicle_sales_car_id", "vehicle_sales", ["car_id"])
    op.create_index("ix_vehicle_sales_listed_at", "vehicle_sales", ["listed_at"])
    op.create_index("ix_vehicle_sales_is_sold", "vehicle_sales", ["is_sold"])

    # Convert to TimescaleDB hypertable (partition by listed_at, monthly chunks)
    op.execute(
        "SELECT create_hypertable('vehicle_sales', 'listed_at', "
        "chunk_time_interval => INTERVAL '1 month')"
    )

    # ── price_predictions ─────────────────────────────────────────────────────
    op.create_table(
        "price_predictions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "car_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cars.id"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("predicted_for", sa.Date, nullable=False),
        sa.Column("predicted_price", sa.Integer, nullable=False),
        sa.Column("confidence_low", sa.Integer, nullable=False),
        sa.Column("confidence_high", sa.Integer, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_price_predictions_car_id_predicted_for",
        "price_predictions",
        ["car_id", "predicted_for"],
    )

    # ── watchlist_items ───────────────────────────────────────────────────────
    op.create_table(
        "watchlist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column(
            "car_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cars.id"),
            nullable=False,
        ),
        sa.Column("target_price", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_watchlist_items_user_id", "watchlist_items", ["user_id"])

    # ── scrape_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "scrape_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("scrape_logs")
    op.drop_table("watchlist_items")
    op.drop_table("price_predictions")
    # vehicle_sales is a hypertable — drop chunks first
    op.execute("SELECT drop_chunks('vehicle_sales', older_than => NOW())")
    op.drop_table("vehicle_sales")
    op.drop_table("cars")
