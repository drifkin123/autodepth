import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
