from app.config.ai_settings import AISettings
from app.services.distillation.orchestrator import distillation_context_metadata
from app.main import app
from app.database import SessionLocal
from app.models import User
from fastapi.testclient import TestClient
from unittest.mock import patch
import inspect
from app.routers.distillation import _process_distillation_run

client = TestClient(app)


def test_default_chunk_chars_is_qwen_context_safe():
    assert AISettings().distillation_chunk_chars == 2000


def test_context_metadata_records_num_ctx():
    assert distillation_context_metadata(AISettings()) == {"num_ctx_used": 2000}


def test_context_metadata_tracks_override():
    settings = AISettings(distillation_chunk_chars=1500)
    assert distillation_context_metadata(settings)["num_ctx_used"] == 1500


def test_chunk_is_positive():
    assert AISettings().distillation_chunk_chars > 0


def test_overlap_remains_bounded():
    settings = AISettings()
    assert settings.distillation_overlap_chars < settings.distillation_chunk_chars


def _book_and_author():
    db = SessionLocal()
    user = User(username="g008-author", role="author")
    db.add(user); db.commit(); user_id = user.id
    book = client.post("/api/books", json={"title": "G008", "author": "Test"}).json()
    db.close()
    return book["id"], user_id


def test_async_true_returns_201_pending_run_id():
    book_id, user_id = _book_and_author()
    try:
        with patch("app.routers.distillation._process_distillation_run") as worker:
            response = client.post(f"/api/distillation/books/{book_id}/start?async=true&distillation_provider=ollama", headers={"X-User-Id": user_id}, files={"file": ("test.txt", b"Chapter 1\ntext", "text/plain")})
        assert response.status_code == 201
        body = response.json()
        assert body["distillation_run_id"] and body["status"] == "pending"
        worker.assert_called_once()
    finally:
        client.delete(f"/api/books/{book_id}"); client.delete(f"/api/books/trash/{book_id}")


def test_async_background_task_receives_provider_and_book():
    book_id, user_id = _book_and_author()
    try:
        with patch("app.routers.distillation._process_distillation_run") as worker:
            response = client.post(f"/api/distillation/books/{book_id}/start?async=true&distillation_provider=ollama", headers={"X-User-Id": user_id}, files={"file": ("test.txt", b"Chapter 1\ntext", "text/plain")})
        assert response.status_code == 201
        args = worker.call_args.args
        assert args[1] == book_id and args[-1] == "ollama"
    finally:
        client.delete(f"/api/books/{book_id}"); client.delete(f"/api/books/trash/{book_id}")


def test_async_response_has_stable_provider_model_fields():
    book_id, user_id = _book_and_author()
    try:
        with patch("app.routers.distillation._process_distillation_run"):
            body = client.post(f"/api/distillation/books/{book_id}/start?async=true&distillation_provider=ollama", headers={"X-User-Id": user_id}, files={"file": ("test.txt", b"Chapter 1\ntext", "text/plain")}).json()
        assert set(("distillation_run_id", "status", "provider_used", "model_used", "artifact_count")).issubset(body)
        assert body["artifact_count"] == 0
    finally:
        client.delete(f"/api/books/{book_id}"); client.delete(f"/api/books/trash/{book_id}")


def test_background_worker_is_async_callable():
    assert inspect.iscoroutinefunction(_process_distillation_run)


def test_start_route_uses_created_status():
    from app.routers.distillation import router
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/start"))
    assert route.status_code == 201
