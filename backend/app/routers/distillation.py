import hashlib, json
from datetime import UTC, datetime
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps.auth import require_author
from app.models import Book, DistillationArtifact, DistillationRun, ProjectNode, StoryEntity, User
from app.config.ai_settings import get_ai_settings
from app.services.distillation.parser import parse_text
from app.services.llm.provider_factory import get_distillation_provider_by_name
from app.services.llm.base import Message
from app.database import SessionLocal
from app.services.distillation.orchestrator import distillation_context_metadata
from app.services.errors import ErrorCode, raise_api_error, classify_provider_error, ApiError

router = APIRouter(prefix="/distillation", tags=["distillation"])

# H-0.4 蒸馏产物 → 正史映射（卡 H 验收修复项 #1）
# - outline → ProjectNode（manuscript 树，章节节点）
# - character / setting / plot / item / lore → StoryEntity（story bible 实体）
DISTILLATION_TO_OUTLINE_NODE = "outline"
OUTLINE_TREE_TYPE = "manuscript"
OUTLINE_NODE_TYPE = "chapter"
ENTITY_ARTIFACT_TYPES = frozenset({"character", "setting", "plot", "item", "lore"})


async def _process_distillation_run(run_id, book_id, parsed, settings, provider_name):
    db = SessionLocal()
    run = db.get(DistillationRun, run_id)
    try:
        provider = get_distillation_provider_by_name(provider_name, settings)
        prompt = {"filename": parsed.source_filename, "chapters": [{"title": c.title, "text": c.text[:settings.distillation_chunk_chars]} for c in parsed.chapters[:settings.distillation_max_blocks]]}
        response = await provider.chat([
            Message("system", "Extract structure only; never reproduce source prose."),
            Message("user", json.dumps(prompt, ensure_ascii=False)),
        ])
        if not (response.content or "").strip():
            raise RuntimeError("empty provider response")
        run.status = "succeeded"; run.finished_at = datetime.now(UTC); run.provider_used = provider.get_provider_name(); run.model_used = provider.get_model_name()
        run.result_counts = {"outline": len(parsed.chapters), **distillation_context_metadata(settings)}
        run.prompt_hash = hashlib.sha256(json.dumps(prompt, ensure_ascii=False).encode()).hexdigest(); run.response_hash = hashlib.sha256(response.content.encode()).hexdigest()
        for chapter in parsed.chapters:
            db.add(DistillationArtifact(run_id=run.id, book_id=book_id, artifact_type="outline", title=chapter.title, payload={"chapter_index": chapter.index, "char_count": len(chapter.text)}, status="candidate", distillation_source="auto", created_by_role="ai"))
        db.commit()
    except Exception as exc:
        run.status = "failed"; run.error_message = str(exc)[:2000]; run.finished_at = datetime.now(UTC); db.commit()
    finally:
        db.close()


def _adopt_into_canon(artifact: DistillationArtifact, db: Session) -> str:
    """将 DistillationArtifact 真写正史；返回新建实体的 canonical_id。
    H-R1：AI 不得直入正史；这里走的是作者显式采纳路径，符合红线。
    """
    payload = artifact.payload or {}
    if artifact.artifact_type == DISTILLATION_TO_OUTLINE_NODE:
        node = ProjectNode(
            book_id=artifact.book_id,
            tree_type=OUTLINE_TREE_TYPE,
            node_type=OUTLINE_NODE_TYPE,
            title=artifact.title[:500],
            position=int(payload.get("chapter_index", 0)),
            status="active",
        )
        db.add(node)
        db.flush()
        return node.id
    if artifact.artifact_type in ENTITY_ARTIFACT_TYPES:
        entity = StoryEntity(
            book_id=artifact.book_id,
            entity_type=artifact.artifact_type,
            name=artifact.title[:300],
            entity_metadata=json.dumps(payload, ensure_ascii=False),
        )
        db.add(entity)
        db.flush()
        return entity.id
    raise_api_error(
        ErrorCode.INTERNAL_ERROR,
        message=f"不支持的 artifact_type: {artifact.artifact_type}",
        context={"artifact_type": artifact.artifact_type, "supported": list(ENTITY_ARTIFACT_TYPES) + [DISTILLATION_TO_OUTLINE_NODE]},
    )


@router.post("/books/{book_id}/start", status_code=201)
async def start(
    book_id: str,
    file: UploadFile = File(...),
    distillation_provider: Optional[str] = Query(None, description="覆盖默认 distillation_provider（ollama/cloudmist/auto）"),
    model: Optional[str] = Query(None, description="覆盖默认 model"),
    async_mode: bool = Query(False, alias="async"),
    background_tasks: BackgroundTasks = None,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
):
    if db.get(Book, book_id) is None:
        raise_api_error(ErrorCode.BOOK_NOT_FOUND, message=f"未找到 book_id={book_id}")
    data = await file.read()
    try:
        parsed = parse_text(data, file.filename or "source.txt")
    except Exception as exc:
        raise_api_error(
            ErrorCode.FILE_PARSE_ERROR,
            message=f"解析文件失败: {file.filename or 'source.txt'}",
            detail=str(exc),
            context={"filename": file.filename, "size_bytes": len(data)},
        )
    settings = get_ai_settings()
    if distillation_provider:
        settings = type(settings)(**{**settings.__dict__, "distillation_provider": distillation_provider})
    if model:
        settings = type(settings)(**{**settings.__dict__, "ollama_model": model})

    if async_mode:
        run = DistillationRun(book_id=book_id, user_id=user.id, source_format=parsed.source_format, source_filename=parsed.source_filename, source_hash=hashlib.sha256(parsed.raw_text.encode()).hexdigest(), total_chars=len(parsed.raw_text), total_chapters=len(parsed.chapters), provider_used=distillation_provider or settings.distillation_provider, model_used=model or settings.ollama_model, status="pending", result_counts=distillation_context_metadata(settings), prompt_hash="0" * 64, response_hash="0" * 64)
        db.add(run); db.commit(); db.refresh(run)
        background_tasks.add_task(_process_distillation_run, run.id, book_id, parsed, settings, distillation_provider or settings.distillation_provider)
        return {"distillation_run_id": run.id, "status": "pending", "provider_used": run.provider_used, "model_used": run.model_used, "artifact_count": 0}

    # ---- Phase F Patch 004: try/except wrap the WHOLE provider lifecycle ----
    # Patch 003 only wrapped the factory call; this version wraps everything
    # from "resolve provider" through "chat().content" so any failure surfaces
    # as a canonical ErrorCode envelope instead of raw HTTP 500.
    provider = None
    try:
        provider = get_distillation_provider_by_name(
            distillation_provider or settings.distillation_provider, settings
        )
        if provider is None:
            raise_api_error(
                ErrorCode.UNKNOWN_PROVIDER,
                message=f"不支持的 distillation_provider: {distillation_provider}",
                context={
                    "requested": distillation_provider,
                    "supported": ["ollama", "cloudmist", "deepseek", "minimax", "dashscope", "doubao"],
                },
            )

        prompt = {
            "filename": parsed.source_filename,
            "chapters": [
                {"title": c.title, "text": c.text[: settings.distillation_chunk_chars]}
                for c in parsed.chapters[: settings.distillation_max_blocks]
            ],
        }
        response = await provider.chat([
            Message("system", "Extract structure only; never reproduce source prose."),
            Message("user", json.dumps(prompt, ensure_ascii=False)),
        ])
        if not (response.content or "").strip():
            raise_api_error(
                ErrorCode.PROVIDER_EMPTY_RESPONSE,
                message=f"{provider.get_provider_name()} 返回空内容",
                context={"provider": provider.get_provider_name(), "model": provider.get_model_name()},
            )
    except ApiError:
        raise
    except Exception as exc:
        provider_name = provider.get_provider_name() if provider else (distillation_provider or "unknown")
        model_name = provider.get_model_name() if provider else "unknown"
        code = classify_provider_error(exc, provider_name, model_name)
        raise_api_error(
            code,
            message=f"{provider_name}/{model_name} 蒸馏失败: {type(exc).__name__}",
            detail=str(exc),
            context={
                "provider": provider_name,
                "model": model_name,
                "exc_type": type(exc).__name__,
            },
        )

    run = DistillationRun(
        book_id=book_id,
        user_id=user.id,
        source_format=parsed.source_format,
        source_filename=parsed.source_filename,
        source_hash=hashlib.sha256(parsed.raw_text.encode()).hexdigest(),
        total_chars=len(parsed.raw_text),
        total_chapters=len(parsed.chapters),
        provider_used=provider.get_provider_name(),
        model_used=provider.get_model_name(),
        status="succeeded",
        finished_at=datetime.now(UTC),
        result_counts={"outline": len(parsed.chapters), **distillation_context_metadata(settings)},
        prompt_hash=hashlib.sha256(json.dumps(prompt, ensure_ascii=False).encode()).hexdigest(),
        response_hash=hashlib.sha256(response.content.encode()).hexdigest(),
    )
    db.add(run)
    db.flush()
    for chapter in parsed.chapters:
        db.add(DistillationArtifact(
            run_id=run.id,
            book_id=book_id,
            artifact_type="outline",
            title=chapter.title,
            payload={"chapter_index": chapter.index, "char_count": len(chapter.text)},
            status="candidate",
            distillation_source="auto",
            created_by_role="ai",
        ))
    db.commit()
    return {
        "distillation_run_id": run.id,
        "status": run.status,
        "provider_used": run.provider_used,
        "model_used": run.model_used,
        "artifact_count": len(parsed.chapters),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(require_author), db: Session = Depends(get_db)):
    row = db.get(DistillationRun, run_id)
    if row is None or row.user_id != user.id:
        raise_api_error(ErrorCode.RUN_NOT_FOUND, message=f"未找到 distillation run_id={run_id}")
    return {"id": row.id, "book_id": row.book_id, "status": row.status, "provider_used": row.provider_used, "result_counts": row.result_counts}


@router.get("/books/{book_id}/staging")
def staging(book_id: str, type: str = "outline", user: User = Depends(require_author), db: Session = Depends(get_db)):
    return [
        {"id": x.id, "type": x.artifact_type, "title": x.title, "payload": x.payload, "status": x.status, "canonical_id": x.payload.get("canonical_id") if isinstance(x.payload, dict) else None}
        for x in db.scalars(select(DistillationArtifact).where(DistillationArtifact.book_id == book_id, DistillationArtifact.artifact_type == type)).all()
    ]


@router.post("/staging/{artifact_id}/adopt")
def adopt(artifact_id: str, user: User = Depends(require_author), db: Session = Depends(get_db)):
    row = db.get(DistillationArtifact, artifact_id)
    if row is None or row.status != "candidate":
        raise_api_error(ErrorCode.STAGING_NOT_FOUND, message=f"未找到 staging_artifact_id={artifact_id}")
    # H-0.4 真写正史：作者显式采纳后，按 artifact_type 路由写入 ProjectNode / StoryEntity
    canonical_id = _adopt_into_canon(row, db)
    # 把 canonical_id 回写到 payload 便于前端追溯
    if isinstance(row.payload, dict):
        row.payload = {**row.payload, "canonical_id": canonical_id}
    row.status = "adopted"
    db.commit()
    return {"id": row.id, "status": row.status, "artifact_type": row.artifact_type, "canonical_id": canonical_id}


@router.post("/staging/{artifact_id}/reject")
def reject(artifact_id: str, user: User = Depends(require_author), db: Session = Depends(get_db)):
    row = db.get(DistillationArtifact, artifact_id)
    if row is None or row.status != "candidate":
        raise_api_error(ErrorCode.STAGING_NOT_FOUND, message=f"未找到 staging_artifact_id={artifact_id}")
    row.status = "rejected"
    db.commit()
    return {"id": row.id, "status": row.status}


# ====================================================================
# Phase H Patch 013: batch adopt-all endpoint
# H-R1 走作者显式采纳路径（_adopt_into_canon 内置 type 校验，不破正史门禁）
# H-R2 原子事务：db.begin_nested() savepoint + 任何失败 rollback（不允许半采纳）
# H-R3 鉴权严格：require_author，不接受任何角色绕过
# H-R4 兼容现有：append-only，不动现有 5 端点任何代码
# H-R5 backend 零外溢：不动 alembic 迁移 / 蒸馏 prompt / provider 实现
# ====================================================================
class _AdoptAllBody(BaseModel):
    artifact_ids: list[str] = []


@router.post("/staging/adopt-all")
def adopt_all(
    body: _AdoptAllBody,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
):
    """批量采纳 staging artifacts。

    - 空列表: 200, {adopted: [], failed: []}
    - 全部成功: 201, {adopted: [{id, artifact_type, canonical_id}], failed: []}
    - 预校验失败(任意 id 不存在或 status != candidate): 422 + STAGING_NOT_FOUND envelope
    - 事务循环失败: 422 + STAGING_NOT_FOUND envelope + 已全部回滚(DB 无新行)
    """
    # 局部 import:不污染模块顶部 imports,保持现有 5 端点 import 顺序零改动
    from fastapi.responses import JSONResponse
    from app.services.errors import build_error

    if not body.artifact_ids:
        return JSONResponse(status_code=200, content={"adopted": [], "failed": []})

    # ---- 预校验:全部 artifact_ids 必须存在且 status=candidate ----
    rows = []
    for art_id in body.artifact_ids:
        row = db.get(DistillationArtifact, art_id)
        if row is None or row.status != "candidate":
            envelope = build_error(
                ErrorCode.STAGING_NOT_FOUND,
                message=f"adopt-all 预校验失败:artifact_id={art_id} 不存在或 status != candidate",
                context={"artifact_ids": body.artifact_ids, "missing_or_non_candidate": art_id},
            )
            return JSONResponse(status_code=422, content=envelope)
        rows.append(row)

    # ---- 事务循环:db.begin_nested() savepoint ----
    adopted: list[dict] = []
    savepoint = db.begin_nested()
    try:
        for row in rows:
            canonical_id = _adopt_into_canon(row, db)
            payload = dict(row.payload) if isinstance(row.payload, dict) else {}
            payload["canonical_id"] = canonical_id
            row.payload = payload
            row.status = "adopted"
            adopted.append({"id": row.id, "artifact_type": row.artifact_type, "canonical_id": canonical_id})
    except ApiError as api_err:
        # H-R2:立即回滚整个 savepoint,不允许半采纳状态
        savepoint.rollback()
        envelope = build_error(
            ErrorCode.STAGING_NOT_FOUND,
            message=f"adopt-all 事务失败,已全部回滚:{api_err.body['error']['message']}",
            detail=str(api_err),
            context={
                "adopted": [],  # 不允许半采纳状态
                "failed": [{"id": r.id, "reason": api_err.body["error"]["message"]} for r in rows],
                "attempted_artifact_ids": [r.id for r in rows],
                "rollback": True,
            },
        )
        return JSONResponse(status_code=422, content=envelope)
    except Exception as exc:
        savepoint.rollback()
        envelope = build_error(
            ErrorCode.STAGING_NOT_FOUND,
            message=f"adopt-all 事务失败,已全部回滚:{type(exc).__name__}",
            detail=str(exc)[:500],
            context={
                "adopted": [],  # 不允许半采纳状态
                "failed": [{"id": r.id, "reason": str(exc)[:200]} for r in rows],
                "attempted_artifact_ids": [r.id for r in rows],
                "rollback": True,
            },
        )
        return JSONResponse(status_code=422, content=envelope)
    else:
        # 全部成功,显式提交 savepoint(释放,后续 db.commit() 持久化)
        savepoint.commit()

    db.commit()
    # 全部成功:201
    return JSONResponse(status_code=201, content={"adopted": adopted, "failed": []})


# ----------------------------------------------------------------------------
# patch-014: export endpoint
# GET /api/distillation/books/{book_id}/export?format=json|md
# - format=json: JSON 列表(UTF-8, application/json)
# - format=md  : Markdown 按 artifact_type 分组(UTF-8, text/markdown)
# - book 不存在 → 404 envelope(BOOK_NOT_FOUND)
# - format 非法 → 400 envelope
# - 未鉴权    → 401(require_author)
# ----------------------------------------------------------------------------
_EXPORT_FORMATS = ("json", "md")


@router.get("/books/{book_id}/export")
def export_artifacts(
    book_id: str,
    format: str = Query(..., description="导出格式:json | md"),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
):
    if format not in _EXPORT_FORMATS:
        raise_api_error(
            ErrorCode.INVALID_MODEL,
            message=f"不支持的 format: {format}",
            context={"field": "format", "requested": format, "supported": list(_EXPORT_FORMATS)},
        )
    if db.get(Book, book_id) is None:
        raise_api_error(ErrorCode.BOOK_NOT_FOUND, message=f"未找到 book_id={book_id}")

    rows = list(
        db.scalars(
            select(DistillationArtifact)
            .where(DistillationArtifact.book_id == book_id)
            .order_by(DistillationArtifact.artifact_type, DistillationArtifact.created_at)
        ).all()
    )

    if format == "json":
        payload = [
            {
                "id": r.id,
                "artifact_type": r.artifact_type,
                "title": r.title,
                "payload": r.payload,
                "status": r.status,
                "canonical_id": (r.payload.get("canonical_id") if isinstance(r.payload, dict) else None),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return Response(content=body, media_type="application/json; charset=utf-8")

    # format == "md":按 artifact_type 分组,每个 type 一个 # 标题
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r.artifact_type, []).append(r)
    md_lines: list = [f"# Distillation export · book_id={book_id}", ""]
    for artifact_type, items in grouped.items():
        md_lines.append(f"# {artifact_type}")
        md_lines.append("")
        for r in items:
            payload_json = json.dumps(r.payload or {}, ensure_ascii=False)
            md_lines.append(f"- **{r.title}** (status: {r.status}, id: {r.id})")
            md_lines.append(f"  - payload: {payload_json}")
        md_lines.append("")
    body = "\n".join(md_lines)
    return Response(content=body, media_type="text/markdown; charset=utf-8")
