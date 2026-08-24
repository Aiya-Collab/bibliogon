import hashlib
from unittest import mock

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AiRun, DistillationArtifact, ProjectNode, StoryEntity, User
from app.services.distillation.parser import parse_text
from app.services.llm.base import LLMResponse

client = TestClient(app)


def test_parser_splits_chapters_and_decodes_gb18030():
    parsed = parse_text("第一章 开始\n正文\n第二章 继续\n内容".encode("gb18030"), "book.txt")
    assert parsed.encoding_detected == "gb18030" and len(parsed.chapters) == 2


def test_distillation_requires_author_and_ai_cannot_adopt():
    db = SessionLocal(); author = User(username="h-author", role="author"); run = AiRun(provider="test"); db.add_all([author, run]); db.commit()
    book = client.post("/api/books", json={"title": "H", "author": "T"}).json()
    try:
        assert client.post(f"/api/distillation/books/{book['id']}/start", files={"file": ("x.txt", b"Chapter 1\ntext")}).status_code == 401
        assert client.post(f"/api/distillation/books/{book['id']}/start", files={"file": ("x.txt", b"Chapter 1\ntext")}, headers={"X-AI-Run-Id": run.id}).status_code == 401
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()


def test_staging_adopt_and_reject_are_author_only():
    db = SessionLocal(); author = User(username="h-author-2", role="author"); db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "H2", "author": "T"}).json()
    try:
        assert client.get(f"/api/distillation/books/{book['id']}/staging").status_code == 401
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()


# H-0.4 验收：adopt 端点必须真写正史，按 artifact_type 路由
# - outline → ProjectNode(manuscript tree, chapter node)
# - character/setting/plot/item/lore → StoryEntity
class _FakeProvider:
    base_url = "https://fake"
    def get_provider_name(self): return "cloudmist"
    def get_model_name(self): return "deepseek-v4-flash-0731"
    async def chat(self, messages, **kwargs):
        return LLMResponse("ok", self.get_model_name(), 1, 1, 1, {})


def _seed_run_with_artifact(author, book_id, artifact_type: str, title: str, payload: dict):
    """手工塞一个 DistillationRun + DistillationArtifact 避免走 provider。"""
    db = SessionLocal()
    from app.models import DistillationRun
    run = DistillationRun(
        book_id=book_id, user_id=author.id, source_format="txt",
        source_filename="t.txt", source_hash="x" * 64,
        total_chars=1, total_chapters=1,
        provider_used="fake", model_used="fake",
        status="succeeded",
        prompt_hash="a" * 64, response_hash="b" * 64,
    )
    db.add(run); db.flush()
    art = DistillationArtifact(
        run_id=run.id, book_id=book_id, artifact_type=artifact_type,
        title=title, payload=payload,
        status="candidate", distillation_source="auto", created_by_role="ai",
    )
    db.add(art); db.commit()
    return db, art.id


def test_adopt_outline_creates_project_node():
    db = SessionLocal(); author = User(username="h-outline", role="author"); db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "OH", "author": "T"}).json()
    try:
        sub_db, art_id = _seed_run_with_artifact(author, book["id"], "outline", "第一章 引子", {"chapter_index": 0, "char_count": 100})
        headers = {"X-User-Id": author.id}
        r = client.post(f"/api/distillation/staging/{art_id}/adopt", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "adopted"
        assert body["artifact_type"] == "outline"
        assert body["canonical_id"]
        # verify ProjectNode was actually created in DB
        node = db.get(ProjectNode, body["canonical_id"])
        assert node is not None
        assert node.book_id == book["id"]
        assert node.tree_type == "manuscript"
        assert node.node_type == "chapter"
        assert node.title == "第一章 引子"
        assert node.position == 0
        assert node.status == "active"
        # DistillationArtifact.status 改了
        art = sub_db.get(DistillationArtifact, art_id)
        assert art.status == "adopted"
        assert art.payload.get("canonical_id") == body["canonical_id"]
        sub_db.close()
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()


def test_adopt_character_creates_story_entity():
    db = SessionLocal(); author = User(username="h-character", role="author"); db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "CH", "author": "T"}).json()
    try:
        sub_db, art_id = _seed_run_with_artifact(author, book["id"], "character", "林黛玉", {"role": "protagonist", "age": 14})
        headers = {"X-User-Id": author.id}
        r = client.post(f"/api/distillation/staging/{art_id}/adopt", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["artifact_type"] == "character"
        entity = db.get(StoryEntity, body["canonical_id"])
        assert entity is not None
        assert entity.book_id == book["id"]
        assert entity.entity_type == "character"
        assert entity.name == "林黛玉"
        import json as _json
        assert _json.loads(entity.entity_metadata) == {"role": "protagonist", "age": 14}
        sub_db.close()
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()


def test_adopt_rejects_unknown_artifact_type():
    db = SessionLocal(); author = User(username="h-unknown", role="author"); db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "UH", "author": "T"}).json()
    try:
        sub_db, art_id = _seed_run_with_artifact(author, book["id"], "garbage_type", "x", {})
        headers = {"X-User-Id": author.id}
        r = client.post(f"/api/distillation/staging/{art_id}/adopt", headers=headers)
        # Patch 004: 不支持类型从 422 → 500 + canonical envelope (INTERNAL_ERROR)
        assert r.status_code == 500
        body = r.json()
        assert body["error"]["code"] == "internal_error"
        assert "不支持的 artifact_type" in body["error"]["message"]
        sub_db.close()
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()


def test_reject_does_not_write_canon():
    """reject 应该只改 DistillationArtifact.status，不能写入 ProjectNode/StoryEntity"""
    db = SessionLocal(); author = User(username="h-reject", role="author"); db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "RJ", "author": "T"}).json()
    try:
        sub_db, art_id = _seed_run_with_artifact(author, book["id"], "outline", "第一章", {"chapter_index": 0})
        from sqlalchemy import select, func
        before = db.scalar(select(func.count()).select_from(ProjectNode).where(ProjectNode.book_id == book["id"]))
        r = client.post(f"/api/distillation/staging/{art_id}/reject", headers={"X-User-Id": author.id})
        assert r.status_code == 200
        after = db.scalar(select(func.count()).select_from(ProjectNode).where(ProjectNode.book_id == book["id"]))
        assert before == after, "reject 不应该创建 ProjectNode"
        sub_db.close()
    finally:
        client.delete(f"/api/books/{book['id']}"); client.delete(f"/api/books/trash/{book['id']}"); db.close()
