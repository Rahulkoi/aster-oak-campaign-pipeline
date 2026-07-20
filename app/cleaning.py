"""Deterministic cleaning: fix what has one unambiguous answer, flag the rest.

Policy:
- null metric = honest missing data -> kept, flagged.
- unparseable or negative metric = invalid -> nulled, flagged.
- row rejected only if it has no usable id, or 3+ of 5 metrics are invalid.
- duplicate ids within a batch: first occurrence wins, rest reported as duplicates.
- channel normalization is semantic and is left to the LLM enrichment step.
"""

import re

from app.schemas import CleanedCampaign, RowOutcome

METRIC_FIELDS = ("spend", "impressions", "clicks", "conversions", "revenue")
INT_FIELDS = {"impressions", "clicks", "conversions"}
# A row with 3+ invalid (not merely missing) metrics is noise, not data.
MAX_INVALID_METRICS = 2

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def parse_metric(value: object) -> tuple[float | None, str | None]:
    """Return (parsed_value, error). Both None means legitimately missing."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"boolean is not a metric: {value!r}"
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        stripped = value.strip().replace(",", "").replace("₹", "").replace("$", "")
        if not _NUMERIC_RE.match(stripped):
            return None, f"unparseable number: {value!r}"
        number = float(stripped)
    else:
        return None, f"unsupported type: {value!r}"
    if number < 0:
        return None, f"negative value: {value!r}"
    return number, None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def clean_campaign(raw: dict) -> RowOutcome:
    campaign_id = _clean_text(raw.get("id"))
    if campaign_id is None:
        return RowOutcome(id=None, status="rejected", reasons=["missing id"])

    flags: list[str] = []
    invalid_reasons: list[str] = []
    metrics: dict[str, float | int | None] = {}

    for field in METRIC_FIELDS:
        parsed, error = parse_metric(raw.get(field))
        if error:
            invalid_reasons.append(f"{field}: {error}")
            flags.append(f"{field}_invalid_set_null")
            metrics[field] = None
        elif parsed is None:
            flags.append(f"{field}_missing")
            metrics[field] = None
        else:
            metrics[field] = int(parsed) if field in INT_FIELDS else parsed

    if len(invalid_reasons) > MAX_INVALID_METRICS:
        return RowOutcome(id=campaign_id, status="rejected", reasons=invalid_reasons)

    name = _clean_text(raw.get("name"))
    if name is None:
        flags.append("name_missing")
    channel_raw = _clean_text(raw.get("channel"))
    if channel_raw is None:
        flags.append("channel_missing")

    campaign = CleanedCampaign(
        id=campaign_id,
        name=name,
        channel_raw=channel_raw,
        description=_clean_text(raw.get("description")),
        flags=flags,
        **metrics,
    )
    return RowOutcome(id=campaign_id, status="cleaned", reasons=invalid_reasons, campaign=campaign)


def clean_batch(raw_campaigns: list[dict]) -> list[RowOutcome]:
    outcomes: list[RowOutcome] = []
    seen_ids: set[str] = set()
    for raw in raw_campaigns:
        outcome = clean_campaign(raw)
        if outcome.id is not None and outcome.id in seen_ids:
            outcome = RowOutcome(
                id=outcome.id,
                status="duplicate",
                reasons=[f"id {outcome.id!r} already seen in this batch; first occurrence kept"],
            )
        elif outcome.id is not None:
            seen_ids.add(outcome.id)
        outcomes.append(outcome)
    return outcomes


def derived_metrics(c: CleanedCampaign) -> dict[str, float | None]:
    """Ratios the LLM gets as context for health scoring. None when undefined."""

    def ratio(num: float | int | None, den: float | int | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return round(num / den, 4)

    return {
        "ctr": ratio(c.clicks, c.impressions),
        "cvr": ratio(c.conversions, c.clicks),
        "roas": ratio(c.revenue, c.spend),
        "cpa": ratio(c.spend, c.conversions),
    }
