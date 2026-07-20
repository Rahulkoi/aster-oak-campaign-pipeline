from app.cleaning import clean_batch, clean_campaign, derived_metrics, parse_metric
from app.schemas import CleanedCampaign


class TestParseMetric:
    def test_plain_numbers_pass_through(self):
        assert parse_metric(185000) == (185000.0, None)
        assert parse_metric(0) == (0.0, None)

    def test_comma_formatted_string_is_coerced(self):
        assert parse_metric("42,500") == (42500.0, None)

    def test_null_is_missing_not_invalid(self):
        assert parse_metric(None) == (None, None)

    def test_garbage_strings_are_invalid(self):
        for garbage in ("N/A", "lots", "many", ""):
            value, error = parse_metric(garbage)
            assert value is None and error is not None

    def test_negative_values_are_invalid(self):
        value, error = parse_metric(-5)
        assert value is None and "negative" in error


class TestCleanCampaign:
    def _row(self, **overrides):
        row = {
            "id": "cmp_x", "name": "Campaign", "channel": "fb", "description": "d",
            "spend": 100, "impressions": 1000, "clicks": 50, "conversions": 5, "revenue": 500,
        }
        row.update(overrides)
        return row

    def test_clean_row_passes_without_flags(self):
        outcome = clean_campaign(self._row())
        assert outcome.status == "cleaned"
        assert outcome.campaign.flags == []

    def test_missing_id_rejects(self):
        assert clean_campaign(self._row(id=None)).status == "rejected"
        assert clean_campaign(self._row(id="  ")).status == "rejected"

    def test_single_invalid_metric_is_salvaged_not_rejected(self):
        outcome = clean_campaign(self._row(spend=-1200))
        assert outcome.status == "cleaned"
        assert outcome.campaign.spend is None
        assert "spend_invalid_set_null" in outcome.campaign.flags

    def test_three_or_more_invalid_metrics_reject_the_row(self):
        outcome = clean_campaign(self._row(spend="N/A", impressions="lots", conversions="many"))
        assert outcome.status == "rejected"
        assert len(outcome.reasons) == 3

    def test_blank_name_is_kept_and_flagged(self):
        outcome = clean_campaign(self._row(name=""))
        assert outcome.status == "cleaned"
        assert outcome.campaign.name is None
        assert "name_missing" in outcome.campaign.flags


class TestCleanBatch:
    def test_duplicate_id_keeps_first_occurrence(self):
        rows = [
            {"id": "cmp_1", "spend": 1},
            {"id": "cmp_1", "spend": 2},
        ]
        outcomes = clean_batch(rows)
        assert outcomes[0].status == "cleaned"
        assert outcomes[0].campaign.spend == 1
        assert outcomes[1].status == "duplicate"

    def test_real_input_file_summary(self):
        import json
        raw = json.load(open("data/campaigns_raw.json"))["campaigns"]
        statuses = [o.status for o in clean_batch(raw)]
        assert statuses.count("cleaned") == 13
        assert statuses.count("rejected") == 1
        assert statuses.count("duplicate") == 1


class TestDerivedMetrics:
    def test_ratios_and_division_by_zero(self):
        campaign = CleanedCampaign(
            id="c", name=None, channel_raw=None, description=None,
            spend=0, impressions=1000, clicks=50, conversions=None, revenue=500,
        )
        metrics = derived_metrics(campaign)
        assert metrics["ctr"] == 0.05
        assert metrics["roas"] is None  # spend 0 -> undefined, not a crash
        assert metrics["cvr"] is None  # conversions missing
