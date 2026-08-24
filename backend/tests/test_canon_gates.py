from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models import AiRun, Canon, CanonDelta, Chapter, Revision, User

client = TestClient(app)


def _setup():
    db = SessionLocal()
    author = User(username="canon-author", role="author")
    ai_run = AiRun(provider="test")
    db.add_all([author, ai_run])
    db.commit()
    book = client.post("/api/books", json={"title": "Canon gates", "author": "T"}).json()
    chapter = client.post(f"/api/books/{book['id']}/chapters", json={"title": "C", "content": "base"}).json()
    return db, author, ai_run, book["id"], chapter["id"]


def _headers(author):
    return {"X-User-Id": author.id}


def _publish(client, author, chapter_id, content):
    headers = _headers(author)
    revision = client.post(f"/api/chapters/{chapter_id}/revisions", json={"content": content}, headers=headers).json()
    evidence = client.post(f"/api/revisions/{revision['id']}/evidence", json={"decision": "approved"}, headers=headers).json()
    published = client.post(f"/api/revisions/{revision['id']}/publish", headers=headers)
    assert published.status_code == 200
    return revision, evidence, published.json()["publish_log_id"]


def _delta(author, chapter_id, revision_id, evidence_id, key="character.fate", payload=None):
    return client.post(f"/api/canon-deltas", json={"source_revision_id": revision_id, "source_evidence_id": evidence_id,
        "fact_key": key, "fact_payload": payload or {"alive": False}}, headers=_headers(author))


def test_author_accept_and_reject_receipts_and_canon_state():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        revision, evidence, _ = _publish(client, author, chapter_id, "canon source")
        accepted = _delta(author, chapter_id, revision["id"], evidence["id"])
        rejected = _delta(author, chapter_id, revision["id"], evidence["id"], "event.outcome", {"result": "lost"})
        assert accepted.status_code == 201 and rejected.status_code == 201
        a = client.post(f"/api/canon-deltas/{accepted.json()['id']}/accept", json={"reason": "confirmed"}, headers=_headers(author))
        r = client.post(f"/api/canon-deltas/{rejected.json()['id']}/reject", json={"reason": "contradiction"}, headers=_headers(author))
        assert a.status_code == 200 and r.status_code == 200
        rows = client.get(f"/api/chapters/{chapter_id}/canon", headers=_headers(author)).json()
        assert len(rows) == 1 and rows[0]["fact_key"] == "character.fate"
        db.expire_all()
        receipt = db.scalar(select(CanonDelta).where(CanonDelta.id == accepted.json()["id"]))
        assert receipt.status == "accepted"
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_ai_can_read_but_cannot_mutate_canon_and_anonymous_is_blocked():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        revision, evidence, _ = _publish(client, author, chapter_id, "source")
        proposed = _delta(author, chapter_id, revision["id"], evidence["id"]).json()
        ai = {"X-AI-Run-Id": ai_run.id}
        assert client.post("/api/canon-deltas", json={"source_revision_id": revision["id"], "fact_key": "x", "fact_payload": {}}, headers=ai).status_code == 403
        assert client.post(f"/api/canon-deltas/{proposed['id']}/accept", headers=ai).status_code == 403
        assert client.post(f"/api/canon-deltas/{proposed['id']}/reject", headers=ai).status_code == 403
        assert client.post(f"/api/chapters/{chapter_id}/rollback", json={"target_timestamp": "2026-01-01T00:00:00Z"}, headers=ai).status_code == 403
        assert client.get(f"/api/chapters/{chapter_id}/canon-deltas", headers=ai).status_code == 200
        assert client.get(f"/api/chapters/{chapter_id}/canon", headers=ai).status_code == 200
        assert client.get(f"/api/chapters/{chapter_id}/rollback-receipts", headers=ai).status_code == 200
        assert client.get(f"/api/chapters/{chapter_id}/canon").status_code == 401
        assert client.post("/api/canon-deltas", json={"source_revision_id": revision["id"], "fact_key": "x", "fact_payload": {}}).status_code == 401
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_rollback_restores_revision_and_prior_canon_and_receipt_lists():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        first, evidence1, target_log = _publish(client, author, chapter_id, "first")
        d1 = _delta(author, chapter_id, first["id"], evidence1["id"], payload={"value": 1}).json()
        assert client.post(f"/api/canon-deltas/{d1['id']}/accept", headers=_headers(author)).status_code == 200
        second, evidence2, second_log = _publish(client, author, chapter_id, "second")
        d2 = _delta(author, chapter_id, second["id"], evidence2["id"], payload={"value": 2}).json()
        assert client.post(f"/api/canon-deltas/{d2['id']}/accept", headers=_headers(author)).status_code == 200
        rolled = client.post(f"/api/chapters/{chapter_id}/rollback", json={"target_log_id": target_log, "reason": "restore"}, headers=_headers(author))
        assert rolled.status_code == 200
        body = rolled.json()
        assert second_log in body["affected_publish_log_ids"] and body["affected_canon_ids"] and body["affected_receipt_ids"]
        assert body["active_revision_id"] == first["id"]
        canon = client.get(f"/api/chapters/{chapter_id}/canon", headers=_headers(author)).json()
        # Both accepted facts occurred after the first publish log and are
        # therefore rolled back with the second revision timeline segment.
        assert canon == []
        assert client.get(f"/api/chapters/{chapter_id}/rollback-receipts", headers=_headers(author)).json()[0]["affected_receipt_ids"]
        db.expire_all()
        assert db.get(Chapter, chapter_id).content == "first"
        assert db.get(Revision, first["id"]).status == "active"
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()


def test_canon_partial_unique_index_is_enforced():
    db, author, ai_run, book_id, chapter_id = _setup()
    try:
        source1 = Revision(chapter_id=chapter_id, content="a", content_hash="a" * 64, status="candidate", created_by_role="author")
        source2 = Revision(chapter_id=chapter_id, content="b", content_hash="b" * 64, status="candidate", created_by_role="author")
        db.add_all([source1, source2])
        db.flush()
        delta1 = CanonDelta(chapter_id=chapter_id, source_revision_id=source1.id, fact_key="x", fact_payload={}, proposed_by_role="author")
        db.add(delta1)
        db.flush()
        one = Canon(chapter_id=chapter_id, active_delta_id=delta1.id, fact_key="x", fact_payload={}, accepted_by_user_id=author.id)
        db.add(one)
        db.commit()
        two_delta = CanonDelta(chapter_id=chapter_id, source_revision_id=source2.id, fact_key="x", fact_payload={}, proposed_by_role="author")
        db.add(two_delta)
        db.flush()
        db.add(Canon(chapter_id=chapter_id, active_delta_id=two_delta.id, fact_key="x", fact_payload={}, accepted_by_user_id=author.id))
        try:
            db.commit()
            assert False, "partial unique index allowed duplicate active fact"
        except IntegrityError:
            db.rollback()
    finally:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
        db.close()
