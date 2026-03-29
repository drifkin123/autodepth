import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VehicleSale(Base):
    __tablename__ = "vehicle_sales"

    # Composite PK required by TimescaleDB (partition column must be in PK).
    # source_url uniqueness is enforced in scraper logic, not as a DB constraint,
    # because TimescaleDB unique indexes must also include the partition column.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cars.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    sale_type: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    asking_price: Mapped[int] = mapped_column(Integer, nullable=False)
    sold_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    car = relationship("Car", lazy="select")

    __table_args__ = (
        PrimaryKeyConstraint("id", "listed_at"),
        Index("ix_vehicle_sales_car_id", "car_id"),
        Index("ix_vehicle_sales_listed_at", "listed_at"),
        Index("ix_vehicle_sales_is_sold", "is_sold"),
        Index("ix_vehicle_sales_source_url", "source_url"),
    )
