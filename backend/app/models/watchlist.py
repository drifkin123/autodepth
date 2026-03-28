import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    car_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cars.id"), nullable=False
    )
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    car = relationship("Car", lazy="select")

    __table_args__ = (
        Index("ix_watchlist_items_user_id", "user_id"),
    )
