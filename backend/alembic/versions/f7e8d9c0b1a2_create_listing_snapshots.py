"""create listing_snapshots

Revision ID: f7e8d9c0b1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7e8d9c0b1a2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asking_price", sa.Integer(), nullable=True),
        sa.Column("mileage", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_listing_snapshots_source_url_scraped_at",
        "listing_snapshots",
        ["source_url", "scraped_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_listing_snapshots_source_url_scraped_at",
        table_name="listing_snapshots",
    )
    op.drop_table("listing_snapshots")
