"""LLM enrichment via forced tool-calling (structured output, never free-text).

The API enforces the JSON shape via the tool schema; we still re-validate
with Pydantic client-side because the model can emit out-of-range values.
One retry on failure, then the row is reported as enrichment-failed --
the caller decides what to do with it (we store it un-enriched).
"""

import json
import time
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


TOOL_NAME = "record_enrichment"
TOOL_DESCRIPTION = "Record the structured enrichment for one marketing campaign."

ENRICH_TOOL = {
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
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


_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    interval = settings.llm_min_interval_seconds
    if interval > 0:
        wait = _last_call_at + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    _last_call_at = time.monotonic()


def _call_anthropic(campaign: CleanedCampaign, client: anthropic.Anthropic) -> dict:
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(campaign)}],
        tools=[ENRICH_TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise EnrichmentFailure("model returned no tool_use block")
    return tool_use.input


def _call_openai_compatible(campaign: CleanedCampaign) -> dict:
    import openai

    client = openai.OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    response = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(campaign)},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": Enrichment.model_json_schema(),
            },
        }],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
    )
    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise EnrichmentFailure("model returned no tool call")
    return json.loads(tool_calls[0].function.arguments)


def enrich_campaign(
    campaign: CleanedCampaign, client: anthropic.Anthropic | None = None
) -> Enrichment:
    use_anthropic = client is not None or settings.llm_provider == "anthropic"
    if use_anthropic and client is None:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    last_error = "unknown"
    for _ in range(MAX_ATTEMPTS):
        try:
            _throttle()
            raw = _call_anthropic(campaign, client) if use_anthropic else _call_openai_compatible(campaign)
        except EnrichmentFailure as exc:
            last_error = exc.reason
            continue
        except Exception as exc:  # provider SDK errors (rate limit, auth, network)
            last_error = f"API error: {exc}"
            # A 429 retried immediately will just 429 again; wait out the window.
            is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower()
            time.sleep(30 if is_rate_limit else 2)
            continue
        try:
            return Enrichment.model_validate(raw)
        except ValidationError as exc:
            last_error = f"schema validation failed: {exc.errors()}"
    raise EnrichmentFailure(last_error)
