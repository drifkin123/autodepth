import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AuctionLot(Base):
    __tablename__ = "auction_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_auction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    auction_status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    sold_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bid_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    make: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    trim: Mapped[str | None] = mapped_column(Text, nullable=True)
    vin: Mapped[str | None] = mapped_column(Text, nullable=True)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exterior_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    interior_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    transmission: Mapped[str | None] = mapped_column(Text, nullable=True)
    drivetrain: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    list_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    detail_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    detail_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    images = relationship(
        "AuctionImage",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="lot",
    )

    __table_args__ = (
        UniqueConstraint("source", "source_auction_id", name="uq_auction_lots_source_id"),
        UniqueConstraint("source", "canonical_url", name="uq_auction_lots_source_url"),
        Index("ix_auction_lots_source_status", "source", "auction_status"),
        Index("ix_auction_lots_source_ended_at", "source", "ended_at"),
        Index("ix_auction_lots_make_model_year", "make", "model", "year"),
        Index("ix_auction_lots_ended_at", "ended_at"),
    )
