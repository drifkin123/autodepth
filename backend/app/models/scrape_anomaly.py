import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ScrapeAnomaly(Base):
    __tablename__ = "scrape_anomalies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scrape_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scrape_run = relationship("ScrapeRun", back_populates="anomalies")

    __table_args__ = (
        Index("ix_scrape_anomalies_run_created", "scrape_run_id", "created_at"),
        Index("ix_scrape_anomalies_source_created", "source", "created_at"),
        Index("ix_scrape_anomalies_severity", "severity"),
        Index("ix_scrape_anomalies_code", "code"),
    )
