# Demo Walkthrough Notes — Aster & Oak Campaign Intelligence

Prep for the ~15-min walkthrough. The brief says you're assessed on four things:
**AI/LLM judgment · Backend fundamentals · Engineering craft · Ownership & communication.**
Everything below maps to those. The one rule they stated: *be ready to explain every
meaningful choice as if the AI assistant hadn't made it for you.*

---

## 1. The 30-second pitch (say this first)

> "It's a backend that turns a messy ad-ops export into structured, scored marketing
> intelligence. The pipeline is four stages: **raw JSON → deterministic cleaning →
> LLM enrichment with structured output → Postgres → REST API.** The core design idea
> is a *division of labour*: code does what has one correct answer, the LLM does only
> what needs judgment, and nothing ever fails silently."

Then draw / point to the data flow:

```
data/campaigns_raw.json
        │  POST /campaigns/ingest
        ▼
[1] clean_batch()          ← deterministic: parse numbers, null/flag junk, dedupe, reject
        ▼
[2] enrich_campaign()      ← LLM (forced tool call): canonical channel, objective, health_score
        ▼
[3] _upsert() → Postgres   ← ON CONFLICT DO UPDATE (idempotent)
        ▼
[4] GET /campaigns?filter  ← retrieval with filters + GET /campaigns/{id}
```

---

## 2. Backend software paradigms (what to name and defend)

### a. Layered / separation-of-concerns architecture
Each file has one job — this is the thing to emphasize:
- `config.py` — settings (env-driven, `pydantic-settings`)
- `database.py` — engine + session lifecycle
- `models.py` — SQLAlchemy ORM table (persistence layer)
- `schemas.py` — Pydantic models (API contract / DTOs)
- `cleaning.py` — deterministic domain logic (pure, no I/O, no DB)
- `llm.py` — the AI integration
- `routers/campaigns.py` — HTTP layer, wires the others together
- `main.py` — app assembly

**Why it matters:** `cleaning.py` is pure functions — no database, no network — so it's
trivially unit-testable (and it is tested). The HTTP layer is thin; the logic lives in
testable modules. This is the classic **"thin controllers, fat services"** idea.

### b. Two-stage pipeline: deterministic-first, LLM-second
The single most important design decision. Talk track:
> "Cleaning splits by *certainty*. `"42,500"` → `42500` has exactly one right answer, so
> code does it — it's free, instant, and 100% reliable. Mapping `fb`, `IG`, `meta ads`
> all to `meta` needs semantic judgment, so that's the LLM's job. Neither tool does the
> other's job. I don't spend an LLM call — which is slow, costs money, and can be wrong —
> on something a regex settles."

### c. Data modeling (Postgres schema)
- **Single `campaigns` table, source `id` as the primary key** (a *natural key*). One
  aggregate, no joins needed at this scale.
- **Raw + enriched columns side by side** (`channel_raw` vs `channel`, plus `flags`
  JSONB). Every LLM output stays *auditable* against the input it came from.
- **Indexes** on `channel` and `health_score` — the two columns the GET filters use.
- `enrichment_status` / `enrichment_error` columns → failures are *queryable*, not lost.
- `created_at` / `updated_at` timestamps with DB-side defaults.
- Honest caveat to volunteer: *"I use `create_all` on startup to keep a 90-minute
  exercise simple; production would use Alembic migrations."*

### d. Idempotency via upsert
`_upsert()` uses Postgres `INSERT ... ON CONFLICT (id) DO UPDATE`. Running ingest twice
updates rows in place instead of duplicating them. **Idempotency is a property of the
data model (natural key + upsert), not of extra bookkeeping code.** This is the stretch
goal "idempotent re-ingest," done by construction.

### e. Dependency injection & resource lifecycle
`get_db()` is a FastAPI dependency (`Depends`) that yields a session and closes it in a
`finally` — the session is guaranteed cleaned up even on error. This is the
**dependency-injection** pattern; it also makes the DB swappable in tests.

### f. Contract-driven API design (Pydantic + FastAPI)
- Request/response shapes are declared as Pydantic models (`IngestSummary`,
  `CampaignOut`). FastAPI validates and serializes against them and **auto-generates
  OpenAPI docs at `/docs`** — good for the live demo.
- RESTful resource design: `POST /campaigns/ingest`, `GET /campaigns` (collection, with
  `channel` and `min_score` query filters), `GET /campaigns/{id}` (single resource,
  404 if missing). Correct HTTP status codes (404, 500).
- `CampaignOut` uses `from_attributes=True` to serialize straight from ORM objects.

### g. Twelve-factor config
Secrets/config come from environment (`.env` via `pydantic-settings`). **The API key is
never hardcoded** — the brief explicitly requires this. Same code runs against Anthropic
or any OpenAI-compatible endpoint by flipping one env var.

---

## 3. AI / LLM design (this is graded hardest — "AI/LLM judgment")

### a. Forced tool-calling for structured output — the headline
> "I don't ask the model for text and parse it. I define a `record_enrichment` *tool*
> whose input schema is generated from a Pydantic model, and set
> `tool_choice` to force the model to call exactly that tool. The API then *guarantees*
> the response is JSON matching the schema — no 'here's your JSON:' preamble to strip,
> no free-text parsing."

The tool schema literally is `Enrichment.model_json_schema()` — **one source of truth**
for the shape, shared by the API contract and client-side validation.

### b. Constrained answer space with enums
`channel` is a `Literal[...]` of 7 values, `objective` a `Literal` of 4. The model must
*map into* my taxonomy — it can't invent a new category like "social-media." Enums turn
an open-ended classification into a closed one.

### c. Defense in depth — validate even guaranteed output
> "Schema conformance is not range conformance. A `health_score` of 150 is shaped
> correctly but wrong. So after the tool call I re-validate with Pydantic
> (`ge=0, le=100`). Trust the boundary, still check it."

### d. Prompt design choices (be specific)
- **One campaign per LLM call.** Keeps one confusing row from contaminating a batch and
  makes retries surgical (re-run just the failed row).
- **System prompt carries the domain knowledge:** the channel-mapping table, objective
  definitions, and — most important — **objective-relative scoring**: an awareness
  campaign isn't punished for low conversions; a zero-spend email flow is healthy;
  rows with no tracking must score conservatively (<50) and *name the missing data in
  the rationale rather than inventing performance.*
- **Do the math in code, not the model.** The user message includes derived ratios
  (CTR, CVR, ROAS, CPA) computed in `cleaning.py`. The model *reasons about* the numbers
  instead of doing arithmetic it's bad at.

### e. Model & provider choices
- Reads model + provider from config. `LLM_PROVIDER` = `anthropic` (native tool calling)
  or `openai` (any OpenAI-compatible endpoint: OpenAI, Groq, Gemini) — same schema, same
  retry loop, same validation either way. Handles "we'll give you a key on the day."

---

## 4. Failure handling (explicitly assessed — "how gracefully you handle model failure")

The brief: *"a single bad campaign or a malformed model response must not sink the whole
batch... record which rows failed and why... return a per-row success/failure summary."*
How each is met:

- **Per-row isolation.** Each row is cleaned and enriched independently in a loop. One
  bad row affects only itself.
- **Cleaning failures → structured outcomes**, not exceptions: `cleaned` / `rejected` /
  `duplicate`, each with `reasons`.
- **LLM failure → retry once**, then store the row anyway with
  `enrichment_status="failed"` and the error message. *"Skipping enrichment beats
  hallucinated enrichment. Data is never lost."*
- **Rate-limit awareness:** a 429 waits out the window (30s) instead of retrying
  instantly into another 429; plus proactive pacing (`llm_min_interval_seconds`) for
  free tiers.
- **Per-row summary** returned by ingest: totals + a row-by-row list of status/reasons/
  flags. Nothing fails silently.

### The clean / reject / flag policy — know these four rules cold
1. **`null` metric = honest missing data** → kept + flagged (`impressions_missing`). The
   SMS row genuinely has no impressions; the influencer flat-fee row has no tracking at
   all. **Missing ≠ wrong.**
2. **Unparseable (`"lots"`, `"N/A"`) or impossible (negative spend)** → that field
   nulled + flagged, row kept. *One bad field shouldn't discard four good ones.*
3. **Row rejected only when untrustworthy as a whole:** no usable `id`, or **3+ of 5
   metrics invalid.** This catches the `cmp_013` "DO NOT USE" draft row **by measuring
   data quality, not by string-matching the name** — a much more defensible rule.
4. **Duplicate `id` in a batch:** first occurrence wins, the duplicate is *reported*,
   not silently dropped.

---

## 5. Map the choices to the actual messy data (they'll ask "show me")

| Row | What's messy | What happens |
|-----|--------------|--------------|
| cmp_002 | `spend` is the string `"42,500"` | code coerces → `42500` |
| cmp_001/002/007/008 | channel `fb`, `Meta`, `IG`, `Facebook Ads` | LLM → `meta` |
| cmp_005 | channel `adwords` | LLM → `google` |
| cmp_003/011 | channel `YouTube`, `yt` | LLM → `youtube` (kept separate from google) |
| cmp_009 | `impressions: null` (SMS) | kept, flagged `impressions_missing` |
| cmp_012 | influencer, all metrics null | kept, flagged; LLM scores conservatively |
| cmp_011 | `name: ""` (blank) | kept, flagged `name_missing` |
| cmp_014 | `spend: -1200` (negative) | nulled + flagged, row salvaged |
| cmp_013 | "DO NOT USE", 4 junk metrics | **rejected** (3+ invalid metrics) |
| cmp_008 (2nd) | duplicate id | **duplicate**, first kept |

Expected batch result (asserted in tests): **13 cleaned, 1 rejected, 1 duplicate.**

---

## 6. Engineering craft

- **Commits tell a story** (brief asks: don't squash into one). Show `git log`:
  scaffold → cleaning → LLM enrichment → persistence+API → tests+README →
  provider support → rate-limit handling. Each commit is a coherent step.
- **Tests** (`pytest`): parsing edge cases (commas, garbage, negatives, null-vs-invalid),
  the clean/reject/flag decisions, dedupe, division-by-zero in derived metrics, and a
  full-file assertion (13/1/1). Covers the stretch "tests around parsing/validation."
- **README** has the required "AI & prompt choices" section.

---

## 7. Likely questions + crisp answers

- **"Why not have the LLM clean everything?"** → Slow, costs money, non-deterministic.
  Never spend an unreliable call on a problem a regex solves reliably and for free.
- **"Why not clean the channel in code with a mapping dict?"** → A dict is brittle
  against unseen variants ("meta ads", future channels). Semantic mapping generalizes;
  that's exactly what an LLM is good at, and the enum keeps it bounded.
- **"What if the model returns health_score 150?"** → Pydantic `ge=0,le=100` rejects it,
  counts as a failed attempt, retries once, else stored un-enriched with the error.
- **"Why store failed rows instead of dropping them?"** → Data loss is worse than missing
  enrichment. The row + its raw metrics are still useful and the failure is queryable.
- **"Is re-ingest safe?"** → Yes — natural key + `ON CONFLICT DO UPDATE`. Idempotent.
- **"Why per-row calls, not one batch call?"** → Failure isolation and surgical retries;
  one malformed row can't corrupt the whole batch's output.
- **"SQLite vs Postgres?"** → Postgres (as required). I use Postgres-specific features:
  JSONB for flags and `ON CONFLICT` upserts.
- **"What would you do with more time?"** → Feed the validation error back to the model on
  retry; parallelize/batch the per-row calls; add `/campaigns/insights` (portfolio-level
  LLM observations); a deterministic self-check (flag high health_score but ROAS < 1);
  Alembic migrations; structured logging.

---

## 8. Live demo script (run these in order)

```bash
docker compose up -d                 # Postgres on host port 5434
source .venv/bin/activate
uvicorn app.main:app --reload
# new terminal:
curl -X POST http://localhost:8000/campaigns/ingest | jq   # show per-row summary: 13/1/1
curl "http://localhost:8000/campaigns?channel=meta&min_score=60" | jq
curl http://localhost:8000/campaigns/cmp_004 | jq          # branded search, high health
curl -X POST http://localhost:8000/campaigns/ingest | jq   # run again → still 13, no dupes (idempotent)
pytest -q                            # green tests
```
Also open **http://localhost:8000/docs** — the auto-generated OpenAPI UI is a strong
visual to click through.

Point out in the ingest output: cmp_013 `rejected`, the 2nd cmp_008 `duplicate`,
cmp_012 with flags + a conservative health_score and a rationale that *names* the
missing tracking.
