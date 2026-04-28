import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RawPage(Base):
    __tablename__ = "raw_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    crawl_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_targets.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    crawl_target = relationship("CrawlTarget", back_populates="raw_pages", lazy="selectin")
    parse_runs = relationship(
        "RawParseRun",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="raw_page",
    )
    lot_links = relationship(
        "RawPageLot",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="raw_page",
    )

    __table_args__ = (
        Index("ix_raw_pages_source_fetched_at", "source", "fetched_at"),
        Index("ix_raw_pages_target_type", "target_type"),
        Index("ix_raw_pages_status_code", "status_code"),
        Index("ix_raw_pages_content_sha256", "content_sha256"),
    )
