import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    """A developer's .env (model, fallback model, pacing, writer switch) must never change unit-test behaviour."""
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "LLM_MIN_INTERVAL_S", "LLM_TIMEOUT_S", "GEMINI_API_VERSION", "RECIPEBOT_WRITER"):
        monkeypatch.delenv(k, raising=False)
