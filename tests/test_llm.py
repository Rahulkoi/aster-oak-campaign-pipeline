from types import SimpleNamespace

import pytest

from app.llm import Enrichment, EnrichmentFailure, enrich_campaign
from app.schemas import CleanedCampaign

CAMPAIGN = CleanedCampaign(
    id="cmp_x", name="Retarget cart abandoners", channel_raw="Meta", description="DPA",
    spend=42500.0, impressions=410000, clicks=15600, conversions=980, revenue=1470000.0,
)

GOOD = {"channel": "meta", "objective": "conversion", "health_score": 88, "rationale": "Strong ROAS."}


class FakeClient:
    """Yields one scripted tool_use input per call; records call count."""

    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        block = SimpleNamespace(type="tool_use", input=self.inputs.pop(0))
        return SimpleNamespace(content=[block])


def test_valid_tool_output_is_parsed():
    result = enrich_campaign(CAMPAIGN, client=FakeClient([GOOD]))
    assert isinstance(result, Enrichment)
    assert result.channel == "meta"
    assert result.health_score == 88


def test_invalid_output_retries_once_then_succeeds():
    bad = {**GOOD, "health_score": 150}
    client = FakeClient([bad, GOOD])
    assert enrich_campaign(CAMPAIGN, client=client).health_score == 88
    assert client.calls == 2


def test_persistent_bad_output_raises_with_reason():
    bad = {**GOOD, "channel": "facebook"}  # not in the canonical enum
    with pytest.raises(EnrichmentFailure) as exc_info:
        enrich_campaign(CAMPAIGN, client=FakeClient([bad, bad]))
    assert "validation failed" in exc_info.value.reason
