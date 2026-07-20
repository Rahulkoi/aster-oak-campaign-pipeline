from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    # Natural key from the source export -> upserts make re-ingest idempotent.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    channel_raw: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)

    spend: Mapped[float | None] = mapped_column(Float)
    impressions: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    conversions: Mapped[int | None] = mapped_column(Integer)
    revenue: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[list] = mapped_column(JSONB, default=list)

    channel: Mapped[str | None] = mapped_column(String, index=True)
    objective: Mapped[str | None] = mapped_column(String)
    health_score: Mapped[int | None] = mapped_column(Integer, index=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    enrichment_status: Mapped[str] = mapped_column(String, default="enriched")
    enrichment_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
