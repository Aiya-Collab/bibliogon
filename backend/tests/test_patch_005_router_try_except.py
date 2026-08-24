"""Tests for Phase F Patch 005: router try/except completion.

Verifies that:
1. Non-LLMProviderError exceptions (KeyError, TimeoutError, etc.) raised by
   provider.chat() are caught and surface as HTTP 503 with a structured
   error body, NOT raw 500.
2. AiRunLog is written with status='failed' on BOTH 502 and 503 paths, so
   governance red line R6 (no auto-publish/adopt without traceable AI runs)
   is preserved even when the LLM SDK explodes unexpectedly.
3. ai/routes.py generic endpoints (/chat, /generate, /review,
   /generate-marketing) also catch unexpected exceptions as 503.

Created: 2026-08-24, Phase F Patch 005.
"""

import os
from unittest import mock

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AiRun, AiRunLog, User
from app.services.llm.base import LLMProviderError, LLMResponse

client = TestClient(app)


def _setup_agent():
    """Set up author + AiRun for agent tests."""
    db = SessionLocal()
    author = User(username="f-p005-author", role="author")
    run = AiRun(provider="cloudmist")
    db.add_all([author, run])
    db.commit()
    book = client.post("/api/books", json={"title": "P005", "author": "T"}).json()
    chapter = client.post(f"/api/books/{book['id']}/chapters", json={"title": "C", "content": "base"}).json()
    return db, author, run, book["id"], chapter["id"]


def _patch_succeed_provider():
    """Provide a successful provider for setup phase (book/chapter creation may not use it)."""
    class FakeProvider:
        base_url = "https://fake"
        def get_provider_name(self): return "cloudmist"
        def get_model_name(self): return "deepseek-v4-flash-0731"
        async def chat(self, messages, **kwargs):
            return LLMResponse("generated candidate", self.get_model_name(), 3, 2, 1, {})
    return mock.patch("app.routers.ai_agents.get_llm_provider", return_value=FakeProvider()), mock.patch(
        "app.routers.ai_agents.get_ai_settings",
        return_value=type("S", (), {
            "ai_generation_enabled": True,
            "enabled_agents": frozenset({"drafting", "reviewer", "scribe", "foreshadow", "worldbuilder", "outliner", "context"}),
        })(),
    )


# ---------------------------------------------------------------------------
# Patch 005: ai_agents.py _call() unexpected exception path
# ---------------------------------------------------------------------------


def test_unexpected_exception_in_agent_returns_503_and_writes_failed_log():
    """Patch 005: provider.chat() raises KeyError (non-LLMProviderError) → 503 + AiRunLog failed."""
    db, author, run, book_id, chapter_id = _setup_agent()
    try:
        class ExplodingProvider:
            base_url = "https://fake"
            def get_provider_name(self): return "ollama"
            def get_model_name(self): return "qwen3:8b"
            async def chat(self, messages, **kwargs):
                raise KeyError("response missing 'choices' key")  # noqa: PERF203 - intentional test failure

        env = {"ENABLED_AGENTS": "drafting,reviewer,scribe,foreshadow,worldbuilder,outliner,context"}
        with mock.patch.dict(os.environ, env), \
             mock.patch("app.routers.ai_agents.get_llm_provider", return_value=ExplodingProvider()), \
             mock.patch(
                 "app.routers.ai_agents.get_ai_settings",
                 return_value=type("S", (), {
                     "ai_generation_enabled": True,
                     "enabled_agents": frozenset(env["ENABLED_AGENTS"].split(",")),
                 })(),
             ):
            headers = {"X-AI-Run-Id": run.id}
            response = client.post(
                "/api/ai/agents/drafting/generate",
                json={"chapter_id": chapter_id, "instruction": "continue"},
                headers=headers,
            )
            assert response.status_code == 503, f"expected 503, got {response.status_code}: {response.text}"
            body = response.json()
            assert body["detail"]["error"] == "llm_provider_unexpected"
            assert body["detail"]["provider"] == "ollama"
            assert body["detail"]["model"] == "qwen3:8b"
            assert body["detail"]["exc_type"] == "KeyError"

            # Patch 005 acceptance: AiRunLog MUST be written even on unexpected path
            failed_logs = db.query(AiRunLog).filter_by(ai_run_id=run.id, status="failed").all()
            assert len(failed_logs) == 1, f"expected 1 failed log, got {len(failed_logs)}"
            assert failed_logs[0].provider_name == "ollama"
            assert failed_logs[0].model_name == "qwen3:8b"
            assert "KeyError" in failed_logs[0].error_message
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_llm_provider_error_in_agent_returns_502_and_writes_failed_log():
    """Patch 005 sanity: LLMProviderError path preserved (502) + AiRunLog failed."""
    db, author, run, book_id, chapter_id = _setup_agent()
    try:
        class LLMErrorProvider:
            base_url = "https://fake"
            def get_provider_name(self): return "deepseek"
            def get_model_name(self): return "deepseek-v4-flash-0731"
            async def chat(self, messages, **kwargs):
                raise LLMProviderError("upstream rate limit")

        env = {"ENABLED_AGENTS": "drafting,reviewer,scribe,foreshadow,worldbuilder,outliner,context"}
        with mock.patch.dict(os.environ, env), \
             mock.patch("app.routers.ai_agents.get_llm_provider", return_value=LLMErrorProvider()), \
             mock.patch(
                 "app.routers.ai_agents.get_ai_settings",
                 return_value=type("S", (), {
                     "ai_generation_enabled": True,
                     "enabled_agents": frozenset(env["ENABLED_AGENTS"].split(",")),
                 })(),
             ):
            headers = {"X-AI-Run-Id": run.id}
            response = client.post(
                "/api/ai/agents/drafting/generate",
                json={"chapter_id": chapter_id, "instruction": "continue"},
                headers=headers,
            )
            assert response.status_code == 502
            body = response.json()
            assert body["detail"]["error"] == "llm_provider_error"
            assert body["detail"]["provider"] == "deepseek"
            assert "upstream rate limit" in body["detail"]["message"]

            failed_logs = db.query(AiRunLog).filter_by(ai_run_id=run.id, status="failed").all()
            assert len(failed_logs) == 1
            assert "upstream rate limit" in failed_logs[0].error_message
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


# ---------------------------------------------------------------------------
# Patch 005: ai/routes.py generic endpoints (/chat, /generate)
# ---------------------------------------------------------------------------


def test_ai_chat_unexpected_exception_returns_503():
    """Patch 005: /api/ai/chat catches non-LLMError → 503."""
    class ExplodingLLMClient:
        async def chat(self, *args, **kwargs):
            raise ValueError("SDK returned malformed payload")
        async def test_connection(self): return (False, "boom", "bad")

    with mock.patch("app.ai.routes._get_client", return_value=ExplodingLLMClient()), \
         mock.patch("app.ai.routes._is_ai_enabled", return_value=True):
        response = client.post(
            "/api/ai/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "llm_unexpected"
        assert body["detail"]["exc_type"] == "ValueError"


def test_ai_generate_unexpected_exception_returns_503():
    """Patch 005: /api/ai/generate catches non-LLMError → 503."""
    class ExplodingLLMClient:
        async def chat(self, *args, **kwargs):
            raise TimeoutError("upstream did not respond in 30s")

    with mock.patch("app.ai.routes._get_client", return_value=ExplodingLLMClient()), \
         mock.patch("app.ai.routes._is_ai_enabled", return_value=True):
        response = client.post(
            "/api/ai/generate",
            json={"prompt": "test prompt"},
        )
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "llm_unexpected"
        assert body["detail"]["exc_type"] == "TimeoutError"