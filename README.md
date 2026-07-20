# Aster & Oak — Campaign Intelligence Pipeline

Turns a messy ad-ops campaign export (`data/campaigns_raw.json`) into structured,
LLM-enriched intelligence served through a FastAPI backend with PostgreSQL.

Pipeline: **raw JSON → deterministic cleaning → LLM enrichment (structured output) → Postgres → API**.

## How to run

```bash
# 1. Start Postgres (host port 5434)
docker compose up -d

# 2. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env   # then set ANTHROPIC_API_KEY (never hardcoded)

# 4. Run the API
uvicorn app.main:app --reload

# 5. Ingest the raw data and query
curl -X POST http://localhost:8000/campaigns/ingest
curl "http://localhost:8000/campaigns?channel=meta&min_score=60"
curl http://localhost:8000/campaigns/cmp_004
```

Interactive docs: http://localhost:8000/docs · Tests: `pytest`

## Key design choices

**Two-stage cleaning: deterministic first, LLM second.** Code fixes only what has
one unambiguous answer (`"42,500"` → `42500`, trimming, blank → null). The LLM does
only what needs semantic judgment: mapping wild channel strings (`fb`, `IG`,
`meta ads`) to a canonical enum, inferring objective, scoring health. Neither tool
does the other's job — deterministic checks are free and reliable; LLM calls are
neither.

**Clean / reject / flag policy** (the heart of the exercise, in `app/cleaning.py`):
- `null` metric = *honest missing data* → kept, flagged (`impressions_missing`).
  The SMS campaign legitimately has no impressions; the influencer flat-fee row has
  no tracking at all. Missing ≠ wrong.
- Unparseable (`"lots"`, `"N/A"`) or impossible (negative spend) = *invalid* →
  field nulled + flagged, row kept. One bad field shouldn't discard four good ones.
- Row **rejected** only when untrustworthy as a whole: missing `id`, or 3+ of 5
  metrics invalid. That catches the `cmp_013` "DO NOT USE" draft row by measuring
  data quality, not by string-matching the name.
- Duplicate `id` within a batch: first occurrence wins; the duplicate is reported,
  not silently dropped.
- Every decision is recorded and returned in the ingest response — nothing fails
  silently.

**Single `campaigns` table, source `id` as primary key.** One aggregate, no joins
needed at this scale. The natural key + `ON CONFLICT DO UPDATE` upsert makes
re-ingest idempotent by construction rather than by bookkeeping. Raw values
(`channel_raw`, flags) are stored alongside enriched values so every LLM output is
auditable against its input. `create_all` on startup keeps the exercise simple;
production would use Alembic migrations.

**Failure isolation.** Each row is cleaned and enriched independently; a bad row or
a misbehaving model response affects only itself. If enrichment fails after retry,
the row is still stored with `enrichment_status="failed"` and the error message —
data is never lost, and failures are queryable.

## AI & prompt choices

**What the model is asked to do** — exactly three judgments per campaign, one
campaign per call: canonical `channel`, funnel `objective`, and a 0–100
`health_score` with a one-sentence rationale. Per-row calls keep one confusing row
from contaminating a batch and make retries surgical.

**Why forced tool-calling** (`tool_choice` on a `record_enrichment` tool, schema
generated from the Pydantic model): the API guarantees JSON matching the schema —
no free-text parsing, no "here's your JSON:" preamble to strip. Enums (`meta`,
`google`, `youtube`, `email`, `sms`, `influencer`, `other`) constrain the answer
space so the model maps variants instead of inventing categories. The response is
still re-validated with Pydantic client-side, because schema conformance doesn't
guarantee range conformance (a `health_score` of 150 arrives shaped correctly).

**Prompt design**: the system prompt carries the channel mapping table, objective
definitions, and — most importantly — *objective-relative* scoring: an awareness
campaign isn't punished for low conversions, a zero-spend email flow is healthy,
and rows with no tracking must be scored conservatively with the missing data
named in the rationale, not papered over. The user message is the cleaned campaign
plus derived ratios (CTR, CVR, ROAS, CPA) computed in code — the model reasons
about arithmetic instead of doing it.

**Failure handling**: one retry on API error or schema violation, then the row is
stored un-enriched with the reason. Skipping enrichment beats hallucinated
enrichment.

**Provider switch**: the exercise provides an Anthropic *or* OpenAI key on the
day, so `LLM_PROVIDER` selects native Anthropic tool calling or any
OpenAI-compatible endpoint (OpenAI, Groq, Gemini) — same schema, same retry
loop, same validation either way.

**With more time**: feed validation errors back to the model on retry; batch or
parallelize the per-row calls; a `/campaigns/insights` portfolio endpoint; a
deterministic self-check (e.g. flag when the model's health score is high but ROAS
< 1); Alembic migrations; structured logging.
