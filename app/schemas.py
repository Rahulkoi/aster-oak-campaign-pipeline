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


class IngestRowResult(BaseModel):
    id: str | None
    status: Literal["ingested", "ingested_unenriched", "rejected", "duplicate"]
    reasons: list[str] = []
    flags: list[str] = []


class IngestSummary(BaseModel):
    total_rows: int
    ingested: int
    ingested_unenriched: int
    rejected: int
    duplicates: int
    rows: list[IngestRowResult]


class CampaignOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str | None
    channel_raw: str | None
    description: str | None
    spend: float | None
    impressions: int | None
    clicks: int | None
    conversions: int | None
    revenue: float | None
    flags: list[str]
    channel: str | None
    objective: str | None
    health_score: int | None
    rationale: str | None
    enrichment_status: str
    enrichment_error: str | None
