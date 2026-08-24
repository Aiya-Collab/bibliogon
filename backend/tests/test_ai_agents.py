import hashlib
import os
from unittest import mock

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AiRun, AiRunLog, Revision, User
from app.services.llm.base import LLMResponse

client = TestClient(app)


def _setup():
    db = SessionLocal()
    author = User(username="f-author", role="author")
    run = AiRun(provider="cloudmist")
    db.add_all([author, run])
    db.commit()
    book = client.post("/api/books", json={"title": "F", "author": "T"}).json()
    chapter = client.post(f"/api/books/{book['id']}/chapters", json={"title": "C", "content": "base"}).json()
    return db, author, run, book["id"], chapter["id"]


def _patch_provider():
    class FakeProvider:
        base_url = "https://fake"
        def get_provider_name(self): return "cloudmist"
        def get_model_name(self): return "deepseek-v4-flash-0731"
        async def chat(self, messages, **kwargs):
            return LLMResponse("generated candidate", self.get_model_name(), 3, 2, 1, {})
    return mock.patch("app.routers.ai_agents.get_llm_provider", return_value=FakeProvider()), mock.patch("app.routers.ai_agents.get_ai_settings", return_value=type("S", (), {"ai_generation_enabled": True, "enabled_agents": frozenset({"drafting", "reviewer", "scribe", "foreshadow", "worldbuilder", "outliner", "context"})})())


def test_drafting_candidate_hash_and_reviewer_no_evidence_write():
    db, author, run, book_id, chapter_id = _setup()
    try:
        with _patch_provider()[0], _patch_provider()[1], mock.patch.dict(os.environ, {"ENABLED_AGENTS": "drafting,reviewer,scribe,foreshadow,worldbuilder,outliner,context"}):
            headers = {"X-AI-Run-Id": run.id}
            draft = client.post("/api/ai/agents/drafting/generate", json={"chapter_id": chapter_id, "instruction": "continue"}, headers=headers)
            assert draft.status_code == 200
            body = draft.json()
            assert body["status"] == "candidate"
            assert body["content_hash"] == hashlib.sha256(body["content"].encode()).hexdigest()
            review = client.post("/api/ai/agents/reviewer/review", json={"revision_id": body["revision_id"]}, headers=headers)
            assert review.status_code == 200
            assert db.query(AiRunLog).count() == 2
            assert db.query(Revision).filter_by(id=body["revision_id"], status="candidate").one()
    finally:
        client.delete(f"/api/books/{book_id}"); client.delete(f"/api/books/trash/{book_id}"); db.close()


def test_agent_role_permissions_and_d_e_gates_remain():
    db, author, run, book_id, chapter_id = _setup()
    try:
        ai = {"X-AI-Run-Id": run.id}
        author_headers = {"X-User-Id": author.id}
        with _patch_provider()[0], _patch_provider()[1], mock.patch.dict(os.environ, {"ENABLED_AGENTS": "drafting,reviewer,scribe,foreshadow,worldbuilder,outliner,context"}):
            for path, payload in [
                ("drafting/generate", {"chapter_id": chapter_id}), ("reviewer/review", {"revision_id": "x"}),
                ("scribe/extract-facts", {"chapter_id": chapter_id}), ("foreshadow/scan", {"chapter_id": chapter_id}),
                ("worldbuilder/check", {"chapter_id": chapter_id}), ("outliner/suggest", {"book_id": book_id}),
                ("context/build", {"book_id": book_id, "scope": "all"}),
            ]:
                assert client.post(f"/api/ai/agents/{path}", json=payload).status_code == 401
                assert client.post(f"/api/ai/agents/{path}", json=payload, headers=author_headers).status_code == 403
            assert client.post("/api/ai/agents/unknown/run", json={}, headers=ai).status_code == 422
            os.environ["ENABLED_AGENTS"] = "drafting"
            assert client.post("/api/ai/agents/worldbuilder/check", json={"chapter_id": chapter_id}, headers=ai).status_code == 403
            os.environ.pop("ENABLED_AGENTS", None)
    finally:
        client.delete(f"/api/books/{book_id}"); client.delete(f"/api/books/trash/{book_id}"); db.close()
