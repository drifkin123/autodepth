import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ScrapeRequestLog(Base):
    __tablename__ = "scrape_request_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scrape_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_delay_seconds: Mapped[float | None] = mapped_column(nullable=True)
    raw_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_lot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scrape_run = relationship("ScrapeRun", back_populates="request_logs")

    __table_args__ = (
        Index("ix_scrape_request_logs_run_created", "scrape_run_id", "created_at"),
        Index("ix_scrape_request_logs_source_created", "source", "created_at"),
        Index("ix_scrape_request_logs_outcome", "outcome"),
        Index("ix_scrape_request_logs_status_code", "status_code"),
    )
