import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models import AiRun, Chapter, Revision, RevisionPublishLog, User

client = TestClient(app)


def _setup():
    db = SessionLocal()
    author = User(username="author-gates", role="author")
    ai_run = AiRun(provider="test")
    db.add_all([author, ai_run])
    db.commit()
    book = client.post("/api/books", json={"title": "Revision gates", "author": "T"}).json()
    chapter = client.post(f"/api/books/{book['id']}/chapters", json={"title": "C", "content": "base"}).json()
    return db, author, ai_run, book["id"], chapter["id"]


def _headers(user_id):
    return {"X-User-Id": user_id}


def test_ai_can_create_candidate_but_cannot_write_or_publish():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        ai = client.post(f"/api/chapters/{chapter_id}/revisions", json={"content": "AI draft"}, headers={"X-AI-Run-Id": ai_run.id})
        assert ai.status_code == 201
        revision_id = ai.json()["id"]
        assert ai.json()["status"] == "candidate"
        patch = client.patch(f"/api/revisions/{revision_id}", json={"content": "overwrite"}, headers={"X-AI-Run-Id": ai_run.id})
        assert patch.status_code == 403
        assert patch.json()["detail"]["error"] == "ai_role_cannot_modify_revision"
        publish = client.post(f"/api/revisions/{revision_id}/publish", headers={"X-AI-Run-Id": ai_run.id})
        assert publish.status_code == 403
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_anonymous_cannot_create_candidate():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        response = client.post(f"/api/chapters/{chapter_id}/revisions", json={"content": "anonymous"})
        assert response.status_code == 401
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_ai_fill_and_bulk_are_author_only():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        ai_headers = {"X-AI-Run-Id": ai_run.id}
        single = client.post(f"/api/books/{book_id}/ai-fill", json={"field_classes": ["marketing"]}, headers=ai_headers)
        assert single.status_code == 403
        bulk = client.post("/api/books/bulk-ai-fill/start", json={"ids": [book_id], "field_classes": ["marketing"]}, headers=ai_headers)
        assert bulk.status_code == 403
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_evidence_hash_and_publish_hash_gate():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        headers = _headers(author.id)
        created = client.post(f"/api/chapters/{chapter_id}/revisions", json={"content": "reviewed"}, headers=headers).json()
        expected = hashlib.sha256(b"reviewed").hexdigest()
        evidence = client.post(f"/api/revisions/{created['id']}/evidence", json={"decision": "approved"}, headers=headers)
        assert evidence.status_code == 201
        assert evidence.json()["reviewed_content_hash"] == expected
        changed = client.patch(f"/api/revisions/{created['id']}", json={"content": "changed after review"}, headers=headers)
        assert changed.status_code == 200
        blocked = client.post(f"/api/revisions/{created['id']}/publish", headers=headers)
        assert blocked.status_code == 422
        assert blocked.json()["detail"]["reason"] == "content_hash_mismatch"
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_unapproved_candidate_is_blocked():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        headers = _headers(author.id)
        created = client.post(f"/api/chapters/{chapter_id}/revisions", json={"content": "pending"}, headers=headers).json()
        blocked = client.post(f"/api/revisions/{created['id']}/publish", headers=headers)
        assert blocked.status_code == 422
        assert blocked.json()["detail"]["reason"] == "evidence_not_approved"
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_author_publish_updates_chapter_and_writes_publish_log():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        headers = _headers(author.id)
        created = client.post(
            f"/api/chapters/{chapter_id}/revisions",
            json={"content": "published content"},
            headers=headers,
        ).json()
        evidence = client.post(
            f"/api/revisions/{created['id']}/evidence",
            json={"decision": "approved"},
            headers=headers,
        ).json()

        response = client.post(f"/api/revisions/{created['id']}/publish", headers=headers)
        assert response.status_code == 200
        assert response.json()["evidence_id"] == evidence["id"]

        db.expire_all()
        published = db.get(Revision, created["id"])
        chapter = db.get(Chapter, chapter_id)
        log = db.scalar(select(RevisionPublishLog).where(RevisionPublishLog.new_active_revision_id == created["id"]))
        assert published.status == "active"
        assert published.published_by_user_id == author.id
        assert chapter.content == "published content"
        assert log is not None
        assert log.chapter_id == chapter_id
        assert log.old_active_revision_id is None
        assert log.new_active_revision_id == created["id"]
        assert log.evidence_id == evidence["id"]
        assert log.published_by_user_id == author.id
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_active_partial_unique_index_is_enforced():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        first = Revision(chapter_id=chapter_id, content="a", content_hash="a" * 64, status="active", created_by_role="author")
        second = Revision(chapter_id=chapter_id, content="b", content_hash="b" * 64, status="active", created_by_role="author")
        db.add(first)
        db.commit()
        db.add(second)
        try:
            db.commit()
            assert False, "partial unique index allowed two active revisions"
        except IntegrityError:
            db.rollback()
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()
