from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers.campaigns import router as campaigns_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_all keeps a 90-minute exercise simple; production would use Alembic.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Aster & Oak Campaign Intelligence API",
    description="Ingests messy ad-ops campaign exports, enriches them with an LLM, and serves structured intelligence.",
    lifespan=lifespan,
)
app.include_router(campaigns_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
