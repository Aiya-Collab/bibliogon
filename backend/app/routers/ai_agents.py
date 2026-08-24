import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.ai_settings import get_ai_settings
from app.database import get_db
from app.deps.auth import check_agent_enabled, require_ai_identity, validate_agent_role
from app.models import AiRun, AiRunLog, Canon, Chapter, ProjectNode, Reference, Revision
from app.services.llm.base import LLMProvider, LLMProviderError, Message
from app.services.llm.provider_factory import get_llm_provider, provider_config_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/agents", tags=["ai-agents"])


class AgentBody(BaseModel):
    chapter_id: str | None = None
    book_id: str | None = None
    revision_id: str | None = None
    instruction: str | None = None
    context_refs: list[str] | None = None
    scope: str | None = None


def _enabled(role: str):
    validate_agent_role(role)
    check_agent_enabled(role)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _provider() -> LLMProvider:
    if not get_ai_settings().ai_generation_enabled:
        raise HTTPException(status_code=403, detail={"error": "ai_generation_disabled"})
    try:
        return get_llm_provider()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"error": "llm_provider_unavailable", "message": str(exc)}) from exc


async def _call(role: str, run: AiRun, prompt: dict, db: Session) -> tuple[Any, Any]:
    """Call the LLM provider for an agent role.

    Patch 005: three-layer try/except so any failure (LLMProviderError, timeout,
    JSON parse, or any unexpected exception) is caught, recorded in AiRunLog,
    and surfaced as a canonical HTTP status (502 for provider-reported errors,
    503 for everything else). Previously any non-LLMProviderError escaped as
    a bare 500 with no audit trail, breaking observability for governance
    red line R6 (no auto-publish/adopt without traceable AI runs).
    """
    provider = _provider()
    provider_name = provider.get_provider_name()
    model_name = provider.get_model_name()
    pcfg_hash = provider_config_hash(provider)
    prompt_hash = _hash(prompt)
    chapter_id = prompt.get("chapter_id")
    try:
        response = await provider.chat([Message("system", f"You are the {role} agent."), Message("user", json.dumps(prompt, ensure_ascii=False))])
        output: Any = response.content
        log = AiRunLog(
            ai_run_id=run.id,
            agent_role=role,
            chapter_id=chapter_id,
            prompt_payload_hash=prompt_hash,
            response_payload_hash=_hash(output),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            status="success",
            provider_name=provider_name,
            model_name=model_name,
            provider_config_hash=pcfg_hash,
        )
        db.add(log)
        return output, response
    except LLMProviderError as exc:
        db.add(
            AiRunLog(
                ai_run_id=run.id,
                agent_role=role,
                chapter_id=chapter_id,
                prompt_payload_hash=prompt_hash,
                response_payload_hash=_hash(""),
                status="failed",
                error_message=str(exc),
                provider_name=provider_name,
                model_name=model_name,
                provider_config_hash=pcfg_hash,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "error": "llm_provider_error",
                "message": str(exc),
                "provider": provider_name,
                "model": model_name,
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 兜底任何意外（超时/JSON 解析/SDK 异常），AiRunLog 必须写
        db.add(
            AiRunLog(
                ai_run_id=run.id,
                agent_role=role,
                chapter_id=chapter_id,
                prompt_payload_hash=prompt_hash,
                response_payload_hash=_hash(""),
                status="failed",
                error_message=f"{type(exc).__name__}: {exc}",
                provider_name=provider_name,
                model_name=model_name,
                provider_config_hash=pcfg_hash,
            )
        )
        db.commit()
        logger.exception(
            "Patch 005: unexpected exception in _call role=%s provider=%s model=%s",
            role,
            provider_name,
            model_name,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "llm_provider_unexpected",
                "message": str(exc),
                "provider": provider_name,
                "model": model_name,
                "exc_type": type(exc).__name__,
            },
        ) from exc


@router.post("/{agent_role}/{action}")
async def run_agent(agent_role: str, action: str, body: AgentBody, response: Response, run: AiRun = Depends(require_ai_identity), db: Session = Depends(get_db)):
    _enabled(agent_role)
    if agent_role == "drafting" and action != "generate":
        raise HTTPException(404, detail={"error": "agent_action_not_found"})
    if agent_role == "reviewer" and action != "review":
        raise HTTPException(404, detail={"error": "agent_action_not_found"})
    if agent_role in {"scribe", "foreshadow", "worldbuilder"} and action not in {"extract-facts", "scan", "check"}:
        raise HTTPException(404, detail={"error": "agent_action_not_found"})
    if agent_role == "outliner" and action != "suggest":
        raise HTTPException(404, detail={"error": "agent_action_not_found"})
    if agent_role == "context" and action != "build":
        raise HTTPException(404, detail={"error": "agent_action_not_found"})
    if agent_role == "drafting":
        chapter = db.get(Chapter, body.chapter_id)
        if chapter is None:
            raise HTTPException(404, detail={"error": "chapter_not_found"})
        prompt = {"chapter_id": body.chapter_id, "instruction": body.instruction or "", "content": chapter.content}
        output, response = await _call(agent_role, run, prompt, db)
        revision = Revision(chapter_id=chapter.id, content=str(output), content_hash=hashlib.sha256(str(output).encode()).hexdigest(), status="candidate", created_by_role="ai", ai_run_id=run.id)
        db.add(revision)
        db.commit()
        response.status_code = 201
        return {"revision_id": revision.id, "content": revision.content, "content_hash": revision.content_hash, "status": revision.status}
    prompt = {"chapter_id": body.chapter_id, "book_id": body.book_id, "revision_id": body.revision_id, "instruction": body.instruction or ""}
    output, _ = await _call(agent_role, run, prompt, db)
    db.commit()
    if agent_role == "reviewer":
        revision = db.get(Revision, body.revision_id)
        suggested_hash = revision.content_hash if revision else ""
        return {"decision": "needs_changes", "rationale": str(output), "suggested_hash": suggested_hash, "concerns": []}
    key = {"scribe": "suggested_facts", "foreshadow": "foreshadows", "worldbuilder": "inconsistencies", "outliner": "suggested_nodes", "context": "context"}[agent_role]
    return {key: str(output) if agent_role != "context" else {"text": str(output)}}


@router.get("/runs")
def list_runs(run: AiRun = Depends(require_ai_identity), db: Session = Depends(get_db)):
    rows = db.scalars(select(AiRunLog).where(AiRunLog.ai_run_id == run.id).order_by(AiRunLog.created_at.desc())).all()
    return [{"id": row.id, "agent_role": row.agent_role, "status": row.status, "provider_name": row.provider_name, "model_name": row.model_name, "created_at": row.created_at.isoformat()} for row in rows]
