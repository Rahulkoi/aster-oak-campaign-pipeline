from typing import Literal

from pydantic import BaseModel


class CleanedCampaign(BaseModel):
    """A campaign after deterministic cleaning, before LLM enrichment."""

    id: str
    name: str | None
    channel_raw: str | None
    description: str | None
    spend: float | None
    impressions: int | None
    clicks: int | None
    conversions: int | None
    revenue: float | None
    flags: list[str] = []


class RowOutcome(BaseModel):
    """Per-row result of the deterministic cleaning pass."""

    id: str | None
    status: Literal["cleaned", "rejected", "duplicate"]
    reasons: list[str] = []
    campaign: CleanedCampaign | None = None
