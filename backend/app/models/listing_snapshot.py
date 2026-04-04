import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asking_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_listing_snapshots_source_url_scraped_at", "source_url", "scraped_at"),
    )
