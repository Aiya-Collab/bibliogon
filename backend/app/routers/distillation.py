import hashlib, json
from datetime import UTC, datetime
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile, File
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
