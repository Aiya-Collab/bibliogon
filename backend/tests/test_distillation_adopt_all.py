"""Phase H Patch 013: POST /api/distillation/staging/adopt-all 端点测试。

4 个 pytest:
1. test_adopt_all_success_3_artifacts        全部采纳 + DB 写入验证
2. test_adopt_all_partial_failure_rollback   含不存在 id → 全部回滚
3. test_adopt_all_empty_list                 空列表 200
4. test_adopt_all_unauthorized                无 token 401

H-R2 原子事务硬要求: 部分失败必须全部回滚,DB 无新行。
H-R3 鉴权严格:        require_author,无 token 直接 401。
"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import (
    DistillationArtifact,
    DistillationRun,
    ProjectNode,
    StoryEntity,
    User,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# helpers (私有,不暴露给其他测试文件)
# ---------------------------------------------------------------------------
def _seed_run_with_artifact(book_id: str, user_id: str, artifact_type: str,
                            title: str, payload: dict) -> str:
    """手工塞一个 DistillationRun + DistillationArtifact(candidate),返回 artifact_id。"""
    db = SessionLocal()
    try:
        run = DistillationRun(
            book_id=book_id, user_id=user_id, source_format="txt",
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
        return art.id
    finally:
        db.close()


def _make_author_and_book(tag: str):
    """创建 author user + book,返回 (user_id, book_id)。"""
    db = SessionLocal()
    try:
        author = User(username=tag, role="author")
        db.add(author); db.commit(); user_id = author.id
    finally:
        db.close()
    book = client.post("/api/books", json={"title": tag, "author": "T"}).json()
    return user_id, book["id"]


def _cleanup(book_id: str, db) -> None:
    """删 book + 关闭 session(每个测试都保证 isolated)。"""
    try:
        client.delete(f"/api/books/{book_id}")
        client.delete(f"/api/books/trash/{book_id}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. 全部采纳: 3 个 artifact(1 outline + 1 character + 1 setting)
# ---------------------------------------------------------------------------
def test_adopt_all_success_3_artifacts():
    db = SessionLocal()
    user_id, book_id = _make_author_and_book("h013-success")
    try:
        outline_id = _seed_run_with_artifact(
            book_id, user_id, "outline", "第一章 引子",
            {"chapter_index": 0, "char_count": 100},
        )
        char_id = _seed_run_with_artifact(
            book_id, user_id, "character", "林黛玉",
            {"role": "protagonist", "age": 14},
        )
        setting_id = _seed_run_with_artifact(
            book_id, user_id, "setting", "荣国府",
            {"era": "Qing"},
        )

        r = client.post(
            "/api/distillation/staging/adopt-all",
            json={"artifact_ids": [outline_id, char_id, setting_id]},
            headers={"X-User-Id": user_id},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["failed"] == []
        assert len(body["adopted"]) == 3

        # 每个 adopted 必须有 id / artifact_type / canonical_id
        by_type = {item["artifact_type"]: item for item in body["adopted"]}
        assert set(by_type.keys()) == {"outline", "character", "setting"}
        for item in body["adopted"]:
            assert item["id"]
            assert item["canonical_id"]

        # ---- DB 验证 ----
        # 1 个 ProjectNode(manuscript/chapter)
        proj_count = db.scalar(
            select(func.count()).select_from(ProjectNode).where(ProjectNode.book_id == book_id)
        )
        assert proj_count == 1

        outline_node = db.get(ProjectNode, by_type["outline"]["canonical_id"])
        assert outline_node is not None
        assert outline_node.tree_type == "manuscript"
        assert outline_node.node_type == "chapter"
        assert outline_node.title == "第一章 引子"
        assert outline_node.position == 0
        assert outline_node.status == "active"

        # 2 个 StoryEntity(character + setting)
        ent_count = db.scalar(
            select(func.count()).select_from(StoryEntity).where(StoryEntity.book_id == book_id)
        )
        assert ent_count == 2

        char_entity = db.get(StoryEntity, by_type["character"]["canonical_id"])
        assert char_entity is not None
        assert char_entity.entity_type == "character"
        assert char_entity.name == "林黛玉"

        setting_entity = db.get(StoryEntity, by_type["setting"]["canonical_id"])
        assert setting_entity is not None
        assert setting_entity.entity_type == "setting"
        assert setting_entity.name == "荣国府"

        # 3 个 artifact status 都被改为 adopted + payload.canonical_id 已回写
        arts = db.scalars(
            select(DistillationArtifact).where(DistillationArtifact.book_id == book_id)
        ).all()
        assert len(arts) == 3
        for a in arts:
            assert a.status == "adopted", f"artifact {a.id} should be adopted"
            assert a.payload is not None and a.payload.get("canonical_id"), \
                f"artifact {a.id} payload.canonical_id should be set"
    finally:
        _cleanup(book_id, db)


# ---------------------------------------------------------------------------
# 2. 部分失败: 3 个 id 中混入 1 个不存在的 → 全部回滚
# ---------------------------------------------------------------------------
def test_adopt_all_partial_failure_rollback():
    db = SessionLocal()
    user_id, book_id = _make_author_and_book("h013-rollback")
    try:
        outline_id = _seed_run_with_artifact(
            book_id, user_id, "outline", "第一章",
            {"chapter_index": 0, "char_count": 50},
        )
        char_id = _seed_run_with_artifact(
            book_id, user_id, "character", "孙悟空",
            {"species": "猴"},
        )
        bad_id = "nonexistent_artifact_id_12345_xyz"

        # baseline: 应该为 0(新建 book)
        before_proj = db.scalar(
            select(func.count()).select_from(ProjectNode).where(ProjectNode.book_id == book_id)
        ) or 0
        before_ent = db.scalar(
            select(func.count()).select_from(StoryEntity).where(StoryEntity.book_id == book_id)
        ) or 0
        before_adopted = db.scalar(
            select(func.count()).select_from(DistillationArtifact).where(
                DistillationArtifact.book_id == book_id,
                DistillationArtifact.status == "adopted",
            )
        ) or 0
        assert before_proj == 0 and before_ent == 0 and before_adopted == 0

        # 提交混有 bad_id 的列表
        r = client.post(
            "/api/distillation/staging/adopt-all",
            json={"artifact_ids": [outline_id, bad_id, char_id]},
            headers={"X-User-Id": user_id},
        )
        assert r.status_code == 422, r.text
        body = r.json()
        # envelope 结构校验
        assert body["error"]["code"] == "staging_not_found", body

        # ---- H-R2: 全部回滚 ----
        after_proj = db.scalar(
            select(func.count()).select_from(ProjectNode).where(ProjectNode.book_id == book_id)
        )
        after_ent = db.scalar(
            select(func.count()).select_from(StoryEntity).where(StoryEntity.book_id == book_id)
        )
        after_adopted = db.scalar(
            select(func.count()).select_from(DistillationArtifact).where(
                DistillationArtifact.book_id == book_id,
                DistillationArtifact.status == "adopted",
            )
        )
        assert after_proj == before_proj, "ProjectNode 不应有新行(全部回滚)"
        assert after_ent == before_ent, "StoryEntity 不应有新行(全部回滚)"
        assert after_adopted == before_adopted, "DistillationArtifact 不应有 adopted 状态"

        # 2 个 candidate artifact 状态保持 candidate(没半采纳)
        arts = db.scalars(
            select(DistillationArtifact).where(DistillationArtifact.book_id == book_id)
        ).all()
        assert len(arts) == 2
        for a in arts:
            assert a.status == "candidate", f"artifact {a.id} 应保持 candidate"
    finally:
        _cleanup(book_id, db)


# ---------------------------------------------------------------------------
# 3. 空列表: 200 + adopted=[]
# ---------------------------------------------------------------------------
def test_adopt_all_empty_list():
    db = SessionLocal()
    user_id, book_id = _make_author_and_book("h013-empty")
    try:
        r = client.post(
            "/api/distillation/staging/adopt-all",
            json={"artifact_ids": []},
            headers={"X-User-Id": user_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"adopted": [], "failed": []}, f"unexpected: {body}"
    finally:
        _cleanup(book_id, db)


# ---------------------------------------------------------------------------
# 4. 未鉴权: 无 token → 401
# ---------------------------------------------------------------------------
def test_adopt_all_unauthorized():
    db = SessionLocal()
    user_id, book_id = _make_author_and_book("h013-401")
    try:
        # 无 X-User-Id header
        r = client.post(
            "/api/distillation/staging/adopt-all",
            json={"artifact_ids": ["any_id_does_not_matter"]},
        )
        assert r.status_code == 401, r.text
    finally:
        _cleanup(book_id, db)