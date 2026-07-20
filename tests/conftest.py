import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def no_llm_throttle(monkeypatch):
    """Unit tests must not inherit pacing/config from the local .env."""
    monkeypatch.setattr(settings, "llm_min_interval_seconds", 0.0)
