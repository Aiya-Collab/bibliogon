"""patch-014 E2E 验证:export 端点输出 JSON + MD(UTF-8)

直接调用 FastAPI TestClient,模拟前端场景:
  1. 创建测试 book + author
  2. 手工塞 1 个 DistillationRun + 3 个不同 artifact_type 的 DistillationArtifact
  3. 调用 GET /api/distillation/books/{book_id}/export?format=json
  4. 调用 GET /api/distillation/books/{book_id}/export?format=md
  5. 写盘到 /tmp/test_export.json 和 /tmp/test_export.md
  6. UTF-8 校验:open() with encoding='utf-8'
  7. cleanup
"""
import json
import os

# 与 conftest.py 对齐:测试环境标记必须在 import app.* 之前
os.environ["BIBLIOGON_TEST"] = "1"
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BIBLIOGON_DATA_DIR", "/tmp/bibliogon-e2e-export")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DistillationArtifact, DistillationRun, User  # noqa: E402

# 初始化 in-memory schema
Base.metadata.create_all(bind=engine)

client = TestClient(app)


def main() -> None:
    db = SessionLocal()
    try:
        # 1. Author + book
        author = User(username="e2e-export", role="author")
        db.add(author); db.commit()
        print(f"[setup] author.id = {author.id}")
        book = client.post("/api/books", json={"title": "E2E Export", "author": "T"}).json()
        book_id = book["id"]
        print(f"[setup] book_id   = {book_id}")

        # 2. Seed 1 DistillationRun + 3 artifacts(1 outline + 1 character + 1 setting)
        run = DistillationRun(
            book_id=book_id, user_id=author.id,
            source_format="txt", source_filename="novel.txt",
            source_hash="x" * 64, total_chars=10, total_chapters=2,
            provider_used="fake", model_used="fake",
            status="succeeded",
            prompt_hash="a" * 64, response_hash="b" * 64,
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
        print(f"[seed]  artifact ids: outline={a1.id}, character={a2.id}, setting={a3.id}")

        # 3. format=json
        r_json = client.get(
            f"/api/distillation/books/{book_id}/export?format=json",
            headers={"X-User-Id": author.id},
        )
        print(f"[json] status={r_json.status_code} content-type={r_json.headers['content-type']} bytes={len(r_json.content)}")
        json_path = "/tmp/test_export.json"
        with open(json_path, "wb") as f:
            f.write(r_json.content)

        # 4. format=md
        r_md = client.get(
            f"/api/distillation/books/{book_id}/export?format=md",
            headers={"X-User-Id": author.id},
        )
        print(f"[md]   status={r_md.status_code} content-type={r_md.headers['content-type']} bytes={len(r_md.content)}")
        md_path = "/tmp/test_export.md"
        with open(md_path, "wb") as f:
            f.write(r_md.content)

        # 5. UTF-8 校验(显式 open(..., encoding='utf-8')逐字节读)
        try:
            text_json = open(json_path, encoding="utf-8").read()
            print(f"[utf8] json ok ({len(text_json)} chars)")
        except UnicodeDecodeError as exc:
            print(f"[utf8] json FAIL: {exc}")
            raise
        try:
            text_md = open(md_path, encoding="utf-8").read()
            print(f"[utf8] md   ok ({len(text_md)} chars)")
        except UnicodeDecodeError as exc:
            print(f"[utf8] md FAIL: {exc}")
            raise

        # 6. 内容 hash 抽样确认(JSON 应有 3 条;MD 应有 3 个 # 标题)
        payload = json.loads(text_json)
        assert isinstance(payload, list) and len(payload) == 3, "json must have 3 items"
        md_h1_count = sum(1 for ln in text_md.splitlines() if ln.startswith("# "))
        print(f"[check] json has {len(payload)} items; md has {md_h1_count} '# ' lines")
        # MD 第一个 # 是总标题,后面 3 个是分组标题 → 共 4 个 '# '
        assert md_h1_count == 4, f"md expected 4 '# ' lines(1 总 + 3 类型), got {md_h1_count}"

        print("[OK] E2E export dual-format verification passed")
    finally:
        try:
            client.delete(f"/api/books/{book_id}")
            client.delete(f"/api/books/trash/{book_id}")
        except Exception:
            pass
        db.close()
        Base.metadata.drop_all(bind=engine)


if __name__ == "__main__":
    main()
