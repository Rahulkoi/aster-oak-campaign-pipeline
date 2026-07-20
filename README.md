# Aster & Oak — Campaign Intelligence Pipeline

Turns a messy ad-ops campaign export (`data/campaigns_raw.json`) into structured,
LLM-enriched intelligence served through a FastAPI backend with PostgreSQL.

## How to run

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env   # then set ANTHROPIC_API_KEY

# 4. Run the API
uvicorn app.main:app --reload

# 5. Ingest the raw data
curl -X POST http://localhost:8000/campaigns/ingest
```

Interactive docs: http://localhost:8000/docs

## Key design choices

_(filled in as the build progresses)_

## AI & prompt choices

_(filled in as the build progresses)_
