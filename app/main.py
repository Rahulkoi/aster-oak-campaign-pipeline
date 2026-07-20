from fastapi import FastAPI

app = FastAPI(
    title="Aster & Oak Campaign Intelligence API",
    description="Ingests messy ad-ops campaign exports, enriches them with an LLM, and serves structured intelligence.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
