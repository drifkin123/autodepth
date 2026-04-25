import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CrawlState(Base):
    __tablename__ = "crawl_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    crawl_mode: Mapped[str] = mapped_column(Text, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auction_ids_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oldest_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_crawl_state_source_mode", "source", "crawl_mode"),)
