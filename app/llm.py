"""LLM enrichment via forced tool-calling (structured output, never free-text).

The API enforces the JSON shape via the tool schema; we still re-validate
with Pydantic client-side because the model can emit out-of-range values.
One retry on failure, then the row is reported as enrichment-failed --
the caller decides what to do with it (we store it un-enriched).
"""

import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.cleaning import derived_metrics
from app.config import settings
from app.schemas import CleanedCampaign

Channel = Literal["meta", "google", "youtube", "email", "sms", "influencer", "other"]
Objective = Literal["awareness", "consideration", "conversion", "retention"]

MAX_ATTEMPTS = 2


class Enrichment(BaseModel):
    channel: Channel = Field(description="Canonical channel the raw channel string maps to.")
    objective: Objective = Field(description="Primary funnel objective inferred from name + description.")
    health_score: int = Field(ge=0, le=100, description="0-100 performance health of the campaign.")
    rationale: str = Field(description="One sentence justifying the health score.")


class EnrichmentFailure(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


ENRICH_TOOL = {
    "name": "record_enrichment",
    "description": "Record the structured enrichment for one marketing campaign.",
    "input_schema": Enrichment.model_json_schema(),
}

SYSTEM_PROMPT = """You are a marketing analyst for a D2C skincare brand, enriching one \
ad-ops campaign row at a time. Record your analysis via the record_enrichment tool.

Channel mapping (raw strings vary wildly):
- meta: Facebook, fb, Meta, Instagram, IG, meta ads
- google: Google search/AdWords/Performance Max (not YouTube)
- youtube: YouTube, yt (kept separate from google: video reach, not search intent)
- email: any email/ESP (e.g. Klaviyo)
- sms: text messaging
- influencer: creator flat-fee / sponsorship deals
- other: anything unmappable or unknown

Objective: infer the PRIMARY funnel stage from name + description:
awareness (reach/brand), consideration (engagement/interest),
conversion (purchase/direct response), retention (existing customers: winback, loyalty, VIP).

Health score 0-100, judged relative to what its objective is supposed to achieve:
- Conversion campaigns: weigh ROAS and CPA heavily.
- Awareness campaigns: cheap reach matters; do not punish low conversions.
- Owned channels (email/sms) with ~zero spend and revenue are healthy.
- Missing/no tracking data: score conservatively (below 50) and say the data is missing
  in the rationale rather than inventing performance.
Currency is INR. The rationale must be one sentence."""


def _build_user_message(campaign: CleanedCampaign) -> str:
    payload = campaign.model_dump()
    payload["derived_metrics"] = derived_metrics(campaign)
    return json.dumps(payload, ensure_ascii=False)


def enrich_campaign(
    campaign: CleanedCampaign, client: anthropic.Anthropic | None = None
) -> Enrichment:
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    last_error = "unknown"
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(campaign)}],
                tools=[ENRICH_TOOL],
                tool_choice={"type": "tool", "name": "record_enrichment"},
            )
        except anthropic.APIError as exc:
            last_error = f"API error: {exc}"
            continue
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            last_error = "model returned no tool_use block"
            continue
        try:
            return Enrichment.model_validate(tool_use.input)
        except ValidationError as exc:
            last_error = f"schema validation failed: {exc.errors()}"
    raise EnrichmentFailure(last_error)
