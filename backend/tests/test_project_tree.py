import json

from fastapi.testclient import TestClient

from app.main import app
from app.models import Reference
from app.services.project_references import resolve_reference
from app.services.project_reference_worker import INTERVAL_SECONDS


def _book(client):
    return client.post("/api/books", json={"title": "Tree", "author": "A"}).json()["id"]


def _chapter(client, book_id, content="one\ntarget\nthree"):
    return client.post(f"/api/books/{book_id}/chapters", json={"title": "C", "content": content}).json()


def _node(client, book_id, **data):
    return client.post(f"/api/books/{book_id}/project-tree", json=data)


def test_manuscript_parent_chain_and_unique_chapter_reference():
    with TestClient(app) as client:
        book = _book(client); chapter = _chapter(client, book)
        volume = _node(client, book, tree_type="manuscript", node_type="volume", title="V").json()
        assert _node(client, book, tree_type="manuscript", node_type="chapter", title="bad", parent_id=volume["id"], ref_chapter_id=chapter["id"]).status_code == 422
        part = _node(client, book, tree_type="manuscript", node_type="part", title="P", parent_id=volume["id"]).json()
        assert _node(client, book, tree_type="manuscript", node_type="chapter", title="C", parent_id=part["id"], ref_chapter_id=chapter["id"]).status_code == 201
        assert _node(client, book, tree_type="manuscript", node_type="chapter", title="dup", parent_id=part["id"], ref_chapter_id=chapter["id"]).status_code == 422


def test_tree_type_rules_and_patch_cannot_change_tree_type():
    with TestClient(app) as client:
        book = _book(client)
        assert _node(client, book, tree_type="manuscript", node_type="note", title="no").status_code == 422
        assert _node(client, book, tree_type="story_bible", node_type="chapter", title="no").status_code == 422
        node = _node(client, book, tree_type="research", node_type="note", title="N").json()
        assert client.patch(f"/api/books/{book}/project-tree/{node['id']}", json={"tree_type": "archive"}).status_code == 200
        assert client.get(f"/api/books/{book}/project-tree").json()[0]["tree_type"] == "research"


def test_reference_resolution_and_patch_trigger():
    with TestClient(app) as client:
        book = _book(client); chapter = _chapter(client, book)
        v = _node(client, book, tree_type="manuscript", node_type="volume", title="V").json(); p = _node(client, book, tree_type="manuscript", node_type="part", title="P", parent_id=v["id"]).json(); c = _node(client, book, tree_type="manuscript", node_type="chapter", title="C", parent_id=p["id"], ref_chapter_id=chapter["id"]).json(); scene = _node(client, book, tree_type="manuscript", node_type="scene", title="S", parent_id=c["id"]).json()
        ref = client.post(f"/api/references/scene/{scene['id']}", json={"chapter_id": chapter["id"], "anchor_before": "one\n", "anchor_at": "target", "anchor_after": "\nthree", "para_index": 1})
        assert ref.status_code == 201
        updated = client.patch(f"/api/books/{book}/chapters/{chapter['id']}", json={"content": "one\ntarget\nthree", "version": chapter["version"]})
        assert updated.status_code == 200
        assert client.post(f"/api/references/resolve?chapter_id={chapter['id']}").json()["resolved"] == 1


def test_rebuild_is_read_only_and_apply_creates_nodes():
    with TestClient(app) as client:
        book = _book(client)
        doc = json.dumps({"type":"doc","content":[{"type":"heading","attrs":{"level":3},"content":[{"type":"text","text":"Three"}]}]})
        chapter = _chapter(client, book, doc)
        before = client.get(f"/api/books/{book}/project-tree").json()
        suggestions = client.post(f"/api/books/{book}/project-tree/rebuild").json()
        assert before == [] and any(x["node_type"] == "part" and x["status"] == "draft_placeholder" for x in suggestions)
        applied = client.post(f"/api/books/{book}/project-tree/rebuild-apply", json={"nodes":[{"node_type":"volume","title":"V"},{"node_type":"part","title":"P","parent_index":0},{"node_type":"chapter","title":"C","parent_index":1,"ref_chapter_id":chapter["id"]}]} )
        assert applied.status_code == 201 and len(applied.json()) == 3


def test_rebuild_apply_replaces_only_explicit_manuscript_node():
    with TestClient(app) as client:
        book = _book(client); ch = _chapter(client, book)
        old = _node(client, book, tree_type="manuscript", node_type="volume", title="Old").json()
        result = client.post(f"/api/books/{book}/project-tree/rebuild-apply", json={"nodes": [{"node_type":"volume", "title":"New", "replace_node_id":old["id"]}]})
        assert result.status_code == 201
        rows = client.get(f"/api/books/{book}/project-tree?tree_type=manuscript").json()
        assert len(rows) == 1 and rows[0]["id"] == old["id"] and rows[0]["title"] == "New"
        foreign = _node(client, book, tree_type="research", node_type="note", title="R").json()
        rejected = client.post(f"/api/books/{book}/project-tree/rebuild-apply", json={"nodes": [{"node_type":"volume", "title":"No", "replace_node_id":foreign["id"]}]})
        assert rejected.status_code == 422


def test_reference_resolution_three_states():
    unique = Reference(anchor_before="a", anchor_at="b", anchor_after="c", para_index=0)
    resolve_reference(unique, "xxabc\n")
    assert unique.status == "valid" and unique.para_index == 0
    multiple = Reference(anchor_before="", anchor_at="hit", anchor_after="", para_index=0)
    resolve_reference(multiple, "hit and hit")
    assert multiple.status == "needs_relocate"
    missing = Reference(anchor_before="", anchor_at="gone", anchor_after="", para_index=0)
    resolve_reference(missing, "present")
    assert missing.status == "broken"


def test_daily_worker_is_independent_24h_loop_contract():
    assert INTERVAL_SECONDS == 24 * 60 * 60
