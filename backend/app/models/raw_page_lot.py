import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RawPageLot(Base):
    __tablename__ = "raw_page_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_pages.id", ondelete="CASCADE"), nullable=False
    )
    auction_lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auction_lots.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    raw_page = relationship("RawPage", back_populates="lot_links", lazy="selectin")
    auction_lot = relationship("AuctionLot", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "raw_page_id",
            "auction_lot_id",
            "relationship_type",
            name="uq_raw_page_lots_page_lot_type",
        ),
        Index("ix_raw_page_lots_lot_id", "auction_lot_id"),
    )
