import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PricePrediction(Base):
    __tablename__ = "price_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cars.id"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_for: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_price: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_low: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_high: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_price_predictions_car_id_predicted_for", "car_id", "predicted_for"),
    )
