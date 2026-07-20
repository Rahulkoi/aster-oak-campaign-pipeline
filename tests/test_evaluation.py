from app.evaluation import CampaignMetrics, check_campaign, evaluate


def m(**kw) -> CampaignMetrics:
    base = dict(id="c", objective="conversion", health_score=50, spend=100.0, revenue=300.0)
    base.update(kw)
    return CampaignMetrics(**base)


class TestCheckCampaign:
    def test_agreement_returns_none(self):
        # ROAS 3.0, score 75 -> consistent, no flag
        assert check_campaign(m(revenue=300.0, health_score=75)) is None

    def test_high_score_on_unprofitable_is_flagged(self):
        # ROAS 0.5, score 80 -> model too generous
        d = check_campaign(m(spend=200.0, revenue=100.0, health_score=80))
        assert d is not None
        assert d.rule == "high_score_despite_unprofitable"
        assert d.roas == 0.5

    def test_low_score_on_strong_roas_is_flagged(self):
        # ROAS 5.0, score 30 -> model too harsh
        d = check_campaign(m(spend=100.0, revenue=500.0, health_score=30))
        assert d is not None
        assert d.rule == "low_score_despite_strong_roas"

    def test_awareness_is_not_judged_on_roas(self):
        # Same unprofitable numbers, but awareness -> intentionally not flagged
        assert check_campaign(m(objective="awareness", spend=200.0, revenue=100.0, health_score=80)) is None

    def test_missing_metrics_are_skipped(self):
        assert check_campaign(m(revenue=None, health_score=80)) is None
        assert check_campaign(m(spend=0.0, health_score=80)) is None
        assert check_campaign(m(health_score=None)) is None


class TestEvaluate:
    def test_report_counts_and_skips(self):
        campaigns = [
            m(id="ok", spend=100.0, revenue=500.0, health_score=90),          # agrees
            m(id="bad", spend=200.0, revenue=100.0, health_score=85),         # flagged
            m(id="awareness", objective="awareness", health_score=90),        # skipped
            m(id="notracking", revenue=None, health_score=40),                # skipped
        ]
        report = evaluate(campaigns)
        assert report.field_checked == "health_score"
        assert report.evaluated == 2
        assert report.skipped == 2
        assert [d.id for d in report.disagreements] == ["bad"]
