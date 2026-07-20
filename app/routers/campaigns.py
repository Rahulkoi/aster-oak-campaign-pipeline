import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.cleaning import clean_batch
from app.database import get_db
from app.evaluation import CampaignMetrics, EvaluationReport, evaluate
from app.llm import EnrichmentFailure, enrich_campaign
from app.models import Campaign
from app.schemas import CampaignOut, ChannelFilter, CleanedCampaign, IngestRowResult, IngestSummary

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

RAW_DATA_PATH = Path("data/campaigns_raw.json")


def _upsert(db: Session, values: dict) -> None:
    stmt = insert(Campaign).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "id"}
    db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols))


def _ingest_row(db: Session, campaign: CleanedCampaign) -> IngestRowResult:
    values = campaign.model_dump()
    try:
        enrichment = enrich_campaign(campaign)
        values.update(enrichment.model_dump(), enrichment_status="enriched", enrichment_error=None)
        status = "ingested"
        reasons: list[str] = []
    except EnrichmentFailure as failure:
        # Store the row anyway: a failed enrichment must not lose the data.
        values.update(enrichment_status="failed", enrichment_error=failure.reason)
        status = "ingested_unenriched"
        reasons = [f"enrichment failed: {failure.reason}"]
    _upsert(db, values)
    return IngestRowResult(id=campaign.id, status=status, reasons=reasons, flags=campaign.flags)


@router.post("/ingest", response_model=IngestSummary)
def ingest(db: Session = Depends(get_db)) -> IngestSummary:
    if not RAW_DATA_PATH.exists():
        raise HTTPException(status_code=500, detail=f"raw data file not found: {RAW_DATA_PATH}")
    raw = json.loads(RAW_DATA_PATH.read_text())["campaigns"]

    rows: list[IngestRowResult] = []
    for outcome in clean_batch(raw):
        if outcome.status == "cleaned":
            rows.append(_ingest_row(db, outcome.campaign))
        else:
            rejected_status = "rejected" if outcome.status == "rejected" else "duplicate"
            rows.append(IngestRowResult(id=outcome.id, status=rejected_status, reasons=outcome.reasons))
    db.commit()

    counts = {s: sum(1 for r in rows if r.status == s) for s in
              ("ingested", "ingested_unenriched", "rejected", "duplicate")}
    return IngestSummary(
        total_rows=len(rows),
        ingested=counts["ingested"],
        ingested_unenriched=counts["ingested_unenriched"],
        rejected=counts["rejected"],
        duplicates=counts["duplicate"],
        rows=rows,
    )


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    channel: ChannelFilter | None = Query(None, description="Filter by canonical channel"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum health score"),
    db: Session = Depends(get_db),
) -> list[Campaign]:
    query = select(Campaign).order_by(Campaign.health_score.desc().nulls_last())
    if channel is not None:
        query = query.where(Campaign.channel == channel.value)
    if min_score is not None:
        query = query.where(Campaign.health_score >= min_score)
    return list(db.scalars(query))


@router.get("/evaluation", response_model=EvaluationReport)
def evaluation(db: Session = Depends(get_db)) -> EvaluationReport:
    """Self-check: flag campaigns whose health_score contradicts their ROAS.

    Registered before /{campaign_id} so 'evaluation' is not read as an id.
    """
    campaigns = db.scalars(select(Campaign)).all()
    metrics = [
        CampaignMetrics(
            id=c.id, objective=c.objective, health_score=c.health_score,
            spend=c.spend, revenue=c.revenue,
        )
        for c in campaigns
    ]
    return evaluate(metrics)


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str, db: Session = Depends(get_db)) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id!r} not found")
    return campaign
