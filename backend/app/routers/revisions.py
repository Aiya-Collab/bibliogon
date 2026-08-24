import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import require_author, require_author_write, require_revision_creator
from app.models import Chapter, Revision, RevisionEvidence, RevisionPublishLog, User

router = APIRouter(tags=["revisions"])


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class RevisionCreate(BaseModel):
    content: str
    parent_revision_id: str | None = None


class RevisionPatch(BaseModel):
    content: str


class EvidenceCreate(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|pending)$")
    rationale: str | None = None
    source_refs: dict | list | None = None


def _revision_or_404(db: Session, revision_id: str) -> Revision:
    revision = db.get(Revision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail={"error": "revision_not_found"})
    return revision


def _json(revision: Revision) -> dict:
    return {
        "id": revision.id,
        "chapter_id": revision.chapter_id,
        "content": revision.content,
        "content_hash": revision.content_hash,
        "parent_revision_id": revision.parent_revision_id,
        "status": revision.status,
        "created_by_role": revision.created_by_role,
        "created_by_user_id": revision.created_by_user_id,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "published_at": revision.published_at.isoformat() if revision.published_at else None,
    }


@router.post("/chapters/{chapter_id}/revisions", status_code=201)
def create_candidate(
    chapter_id: str,
    data: RevisionCreate,
    identity: tuple[str, User | None, object | None] = Depends(require_revision_creator),
    db: Session = Depends(get_db),
):
    role, user, ai_run = identity
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail={"error": "chapter_not_found"})
    revision = Revision(
        chapter_id=chapter_id,
        content=data.content,
        content_hash=content_hash(data.content),
        parent_revision_id=data.parent_revision_id,
        status="candidate",
        created_by_role=role,
        created_by_user_id=user.id if user else None,
        ai_run_id=ai_run.id if ai_run else None,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return _json(revision)


@router.post("/revisions/{revision_id}/evidence", status_code=201)
def create_evidence(
    revision_id: str,
    data: EvidenceCreate,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
):
    revision = _revision_or_404(db, revision_id)
    evidence = RevisionEvidence(
        revision_id=revision.id,
        reviewed_content_hash=content_hash(revision.content),
        decision=data.decision,
        reviewer_role=user.role,
        reviewer_user_id=user.id,
        rationale=data.rationale,
        source_refs=data.source_refs,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return {"id": evidence.id, "revision_id": revision.id, "reviewed_content_hash": evidence.reviewed_content_hash, "decision": evidence.decision}


@router.patch("/revisions/{revision_id}")
def patch_revision(
    revision_id: str,
    data: RevisionPatch,
    user: User = Depends(require_author_write),
    db: Session = Depends(get_db),
):
    revision = _revision_or_404(db, revision_id)
    revision.content = data.content
    revision.content_hash = content_hash(data.content)
    db.commit()
    db.refresh(revision)
    return _json(revision)


@router.post("/revisions/{revision_id}/publish")
def publish_revision(
    revision_id: str,
    user: User = Depends(require_author_write),
    db: Session = Depends(get_db),
):
    revision = _revision_or_404(db, revision_id)
    if revision.status != "candidate":
        raise HTTPException(status_code=422, detail={"error": "publish_blocked", "reason": "revision_not_candidate"})
    evidence = db.scalar(select(RevisionEvidence).where(RevisionEvidence.revision_id == revision.id, RevisionEvidence.decision == "approved").order_by(RevisionEvidence.reviewed_at.desc()))
    if evidence is None:
        raise HTTPException(status_code=422, detail={"error": "publish_blocked", "reason": "evidence_not_approved"})
    if evidence.reviewed_content_hash != revision.content_hash:
        raise HTTPException(status_code=422, detail={"error": "publish_blocked", "reason": "content_hash_mismatch"})
    chapter = db.get(Chapter, revision.chapter_id)
    old_active = db.scalar(select(Revision).where(Revision.chapter_id == revision.chapter_id, Revision.status == "active"))
    if old_active is not None:
        old_active.status = "archived"
        # Clear the partial unique-index slot before activating the new row.
        db.flush()
    revision.status = "active"
    revision.published_at = datetime.now(UTC)
    revision.published_by_user_id = user.id
    chapter.content = revision.content
    log = RevisionPublishLog(chapter_id=revision.chapter_id, published_by_user_id=user.id, old_active_revision_id=old_active.id if old_active else None, new_active_revision_id=revision.id, evidence_id=evidence.id)
    db.add(log)
    db.commit()
    return {"revision": _json(revision), "publish_log_id": log.id, "evidence_id": evidence.id}
