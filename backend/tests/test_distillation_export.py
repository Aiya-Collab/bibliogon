"""patch-014: export 端点 pytest(4 用例)

- GET /api/distillation/books/{book_id}/export?format=json|md
- format=json → UTF-8 application/json 列表
- format=md   → UTF-8 text/markdown,按 artifact_type 分组
- book 不存在 → 404 + envelope
- 未鉴权      → 401
"""
import json

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import DistillationArtifact, DistillationRun, User

client = TestClient(app)


def _seed_run_with_3_artifacts(author, book_id: str):
    """手工塞 1 个 DistillationRun + 3 个不同类型的 DistillationArtifact。

    返回 (sub_db_session, [id_outline, id_character, id_setting])
    """
    db = SessionLocal()
    run = DistillationRun(
        book_id=book_id,
        user_id=author.id,
        source_format="txt",
        source_filename="novel.txt",
        source_hash="x" * 64,
        total_chars=10,
        total_chapters=2,
        provider_used="fake",
        model_used="fake",
        status="succeeded",
        prompt_hash="a" * 64,
        response_hash="b" * 64,
    )
    db.add(run); db.flush()
    a1 = DistillationArtifact(
        run_id=run.id, book_id=book_id, artifact_type="outline",
        title="第一章 引子", payload={"chapter_index": 0, "char_count": 100},
        status="candidate", distillation_source="auto", created_by_role="ai",
    )
    a2 = DistillationArtifact(
        run_id=run.id, book_id=book_id, artifact_type="character",
        title="林黛玉", payload={"role": "protagonist", "age": 14},
        status="candidate", distillation_source="auto", created_by_role="ai",
    )
    a3 = DistillationArtifact(
        run_id=run.id, book_id=book_id, artifact_type="setting",
        title="荣国府", payload={"location": "金陵"},
        status="candidate", distillation_source="auto", created_by_role="ai",
    )
    db.add_all([a1, a2, a3]); db.commit()
    return db, [a1.id, a2.id, a3.id]


def _make_book_and_author():
    db = SessionLocal()
    author = User(username="h-export", role="author")
    db.add(author); db.commit()
    book = client.post("/api/books", json={"title": "EXPORT", "author": "T"}).json()
    return db, author, book


def _cleanup(db, book_id: str):
    try:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
    finally:
        db.close()


def test_export_json_3_artifacts():
    """JSON 输出结构 + UTF-8 校验:3 个 artifact,验证 payload / status / canonical_id 字段"""
    db, author, book = _make_book_and_author()
    try:
        sub_db, art_ids = _seed_run_with_3_artifacts(author, book["id"])
        r = client.get(
            f"/api/distillation/books/{book['id']}/export?format=json",
            headers={"X-User-Id": author.id},
        )
        assert r.status_code == 200, r.text
        # Content-Type 必须是 application/json; charset=utf-8
        assert "application/json" in r.headers["content-type"]
        assert "utf-8" in r.headers["content-type"].lower()
        # 字节流解码不应抛 UnicodeDecodeError(UTF-8 校验)
        raw_bytes = r.content
        text = raw_bytes.decode("utf-8")  # 若非 UTF-8 → UnicodeDecodeError
        payload = json.loads(text)
        assert isinstance(payload, list)
        assert len(payload) == 3, f"expected 3 artifacts, got {len(payload)}"
        # 每个元素都有 id / artifact_type / title / payload / status / canonical_id / created_at
        required_keys = {"id", "artifact_type", "title", "payload", "status", "canonical_id", "created_at"}
        for item in payload:
            assert required_keys.issubset(item.keys()), f"missing keys in {item}"
        types_seen = sorted({x["artifact_type"] for x in payload})
        assert types_seen == ["character", "outline", "setting"]
        # payload 字段验证(取 outline 一条)
        outline_item = next(x for x in payload if x["artifact_type"] == "outline")
        assert outline_item["title"] == "第一章 引子"
        assert outline_item["payload"] == {"chapter_index": 0, "char_count": 100}
        assert outline_item["status"] == "candidate"
        assert outline_item["canonical_id"] is None  # 未采纳
        sub_db.close()
    finally:
        _cleanup(db, book["id"])


def test_export_md_3_artifacts():
    """MD 分组正确:2 个不同 type 应有 2 个 # 标题(outline + character + setting 共 3 个标题行)

    格式规范:每个 artifact_type 一个 `# {type}` 标题 + 每条 `- **{title}** (status: ..., id: ...)`
    """
    db, author, book = _make_book_and_author()
    try:
        sub_db, art_ids = _seed_run_with_3_artifacts(author, book["id"])
        r = client.get(
            f"/api/distillation/books/{book['id']}/export?format=md",
            headers={"X-User-Id": author.id},
        )
        assert r.status_code == 200, r.text
        # Content-Type 必须是 text/markdown; charset=utf-8
        assert "text/markdown" in r.headers["content-type"]
        assert "utf-8" in r.headers["content-type"].lower()
        # 字节流解码不应抛 UnicodeDecodeError(UTF-8 校验)
        text = r.content.decode("utf-8")
        # 校验 MD 分组:3 个 artifact_type 各自 `# {type}` 标题
        lines = text.splitlines()
        type_header_lines = [ln for ln in lines if ln.startswith("# ")]
        # 第一个是 `# Distillation export · book_id=...`,后面 3 个是分组标题
        assert len(type_header_lines) >= 4, f"expected at least 4 '# ' lines, got {len(type_header_lines)}"
        # 提取分组标题(去掉首行总标题)
        group_titles = type_header_lines[1:]
        group_types = {ln.lstrip("# ").strip() for ln in group_titles}
        assert group_types == {"character", "outline", "setting"}, f"got {group_types}"
        # 每条 artifact 一行项目符号: `- **title** (status: ..., id: ...)`
        bullet_lines = [ln for ln in lines if ln.startswith("- **")]
        assert len(bullet_lines) == 3, f"expected 3 bullets, got {len(bullet_lines)}"
        # 一条详情 line 含 `payload:` 子项
        payload_lines = [ln for ln in lines if ln.strip().startswith("- payload:")]
        assert len(payload_lines) == 3, f"expected 3 payload lines, got {len(payload_lines)}"
        # 字面包含关键 title
        assert "林黛玉" in text
        assert "荣国府" in text
        assert "第一章 引子" in text
        sub_db.close()
    finally:
        _cleanup(db, book["id"])


def test_export_book_not_found_404():
    """book_id 不存在 → 404 + envelope(BOOK_NOT_FOUND)"""
    db, author, book = _make_book_and_author()
    try:
        # 用一个合成的、不存在但形式合法的 book_id(32 位)
        fake_book_id = "0" * 32
        r = client.get(
            f"/api/distillation/books/{fake_book_id}/export?format=json",
            headers={"X-User-Id": author.id},
        )
        assert r.status_code == 404, r.text
        body = r.json()
        assert "error" in body, f"missing error envelope: {body}"
        assert body["error"]["code"] == "book_not_found"
        assert fake_book_id in body["error"]["message"]
    finally:
        _cleanup(db, book["id"])


def test_export_unauthorized_401():
    """未鉴权 → 401(require_author 失效)

    既不带 X-User-Id,也不带任何鉴权 header → 应返回 401。
    """
    db, author, book = _make_book_and_author()
    try:
        # 不传任何鉴权 header
        r = client.get(f"/api/distillation/books/{book['id']}/export?format=json")
        assert r.status_code == 401, r.text
    finally:
        _cleanup(db, book["id"])
