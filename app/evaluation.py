"""Lightweight self-check (eval) for the LLM's health_score.

We can't manually review every model output, so we guard one enriched field
against a deterministic rule and flag disagreements for human review. This
does not correct the model -- it surfaces where model judgment and the hard
numbers diverge.

Chosen field: health_score. Ground-truth signal: ROAS (revenue / spend).
Scope: only campaigns whose objective is revenue-driven (conversion,
retention). Awareness/consideration campaigns are intentionally NOT judged on
ROAS -- that matches how the enrichment prompt was told to score them.
"""

from typing import Literal

from pydantic import BaseModel

REVENUE_DRIVEN = {"conversion", "retention"}

# Thresholds are deliberately conservative so we only flag clear disagreements.
UNPROFITABLE_ROAS = 1.0   # spending more than it earns
HIGH_SCORE = 70
STRONG_ROAS = 4.0
LOW_SCORE = 40


class CampaignMetrics(BaseModel):
    id: str
    objective: str | None
    health_score: int | None
    spend: float | None
    revenue: float | None


class Disagreement(BaseModel):
    id: str
    rule: str
    detail: str
    health_score: int
    roas: float


class EvaluationReport(BaseModel):
    field_checked: Literal["health_score"] = "health_score"
    evaluated: int
    skipped: int
    disagreements: list[Disagreement]


def _roas(spend: float | None, revenue: float | None) -> float | None:
    if spend is None or revenue is None or spend <= 0:
        return None
    return round(revenue / spend, 2)


def check_campaign(c: CampaignMetrics) -> Disagreement | None:
    """Return a Disagreement if the model's score contradicts ROAS, else None."""
    if c.health_score is None or c.objective not in REVENUE_DRIVEN:
        return None
    roas = _roas(c.spend, c.revenue)
    if roas is None:
        return None

    if roas < UNPROFITABLE_ROAS and c.health_score >= HIGH_SCORE:
        return Disagreement(
            id=c.id, rule="high_score_despite_unprofitable",
            detail=f"ROAS {roas} < {UNPROFITABLE_ROAS} but health_score {c.health_score} >= {HIGH_SCORE}",
            health_score=c.health_score, roas=roas,
        )
    if roas >= STRONG_ROAS and c.health_score <= LOW_SCORE:
        return Disagreement(
            id=c.id, rule="low_score_despite_strong_roas",
            detail=f"ROAS {roas} >= {STRONG_ROAS} but health_score {c.health_score} <= {LOW_SCORE}",
            health_score=c.health_score, roas=roas,
        )
    return None


def evaluate(campaigns: list[CampaignMetrics]) -> EvaluationReport:
    disagreements: list[Disagreement] = []
    evaluated = 0
    for c in campaigns:
        if c.health_score is None or c.objective not in REVENUE_DRIVEN or _roas(c.spend, c.revenue) is None:
            continue
        evaluated += 1
        found = check_campaign(c)
        if found is not None:
            disagreements.append(found)
    return EvaluationReport(
        evaluated=evaluated,
        skipped=len(campaigns) - evaluated,
        disagreements=disagreements,
    )
