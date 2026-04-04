"""enrich vehicle_sales

Revision ID: a1b2c3d4e5f6
Revises: b63cfeaadd05
Create Date: 2026-04-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "b63cfeaadd05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns to vehicle_sales
    op.add_column("vehicle_sales", sa.Column("make", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("model", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("trim", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("vin", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("transmission", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("no_reserve", sa.Boolean(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("body_style", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("fuel_type", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("location", sa.Text(), nullable=True))
    op.add_column("vehicle_sales", sa.Column("stock_type", sa.Text(), nullable=True))
    op.add_column(
        "vehicle_sales",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Make car_id nullable — use raw SQL because vehicle_sales is a TimescaleDB
    # hypertable and op.alter_column() cannot modify nullability directly on one.
    op.execute("ALTER TABLE vehicle_sales ALTER COLUMN car_id DROP NOT NULL")

    # Composite index to support make/model/trim filtering without car_id
    op.create_index(
        "ix_vehicle_sales_make_model_trim",
        "vehicle_sales",
        ["make", "model", "trim"],
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_sales_make_model_trim", table_name="vehicle_sales")

    # Restore NOT NULL on car_id — requires all existing rows to have a value;
    # in practice downgrade should only run on a clean dev database.
    op.execute("ALTER TABLE vehicle_sales ALTER COLUMN car_id SET NOT NULL")

    op.drop_column("vehicle_sales", "last_seen_at")
    op.drop_column("vehicle_sales", "stock_type")
    op.drop_column("vehicle_sales", "location")
    op.drop_column("vehicle_sales", "fuel_type")
    op.drop_column("vehicle_sales", "body_style")
    op.drop_column("vehicle_sales", "no_reserve")
    op.drop_column("vehicle_sales", "transmission")
    op.drop_column("vehicle_sales", "vin")
    op.drop_column("vehicle_sales", "trim")
    op.drop_column("vehicle_sales", "model")
    op.drop_column("vehicle_sales", "make")
