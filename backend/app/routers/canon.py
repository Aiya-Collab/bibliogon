from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import require_canon_author, require_canon_reader
from app.models import (
    AcceptanceReceipt,
    AiRun,
    Canon,
    CanonDelta,
    Chapter,
    Revision,
    RevisionEvidence,
    RevisionPublishLog,
    RollbackReceipt,
    User,
)

router = APIRouter(tags=["canon"])


class DeltaCreate(BaseModel):
    source_revision_id: str
    source_evidence_id: str | None = None
    fact_key: str
    fact_payload: dict


class DecisionBody(BaseModel):
    reason: str | None = None


class RollbackBody(BaseModel):
    target_log_id: str | None = None
    target_timestamp: datetime | None = None
    reason: str | None = None


def _delta_json(delta: CanonDelta) -> dict:
    return {"id": delta.id, "chapter_id": delta.chapter_id, "source_revision_id": delta.source_revision_id,
            "source_evidence_id": delta.source_evidence_id, "fact_key": delta.fact_key,
            "fact_payload": delta.fact_payload, "status": delta.status,
            "proposed_by_role": delta.proposed_by_role, "proposed_at": delta.proposed_at.isoformat()}


def _canon_json(row: Canon) -> dict:
    return {"id": row.id, "chapter_id": row.chapter_id, "active_delta_id": row.active_delta_id,
            "fact_key": row.fact_key, "fact_payload": row.fact_payload,
            "accepted_by_user_id": row.accepted_by_user_id, "accepted_at": row.accepted_at.isoformat(),
            "rolled_back_at": row.rolled_back_at.isoformat() if row.rolled_back_at else None}


@router.post("/canon-deltas", status_code=201)
def create_delta(data: DeltaCreate, user: User = Depends(require_canon_author), db: Session = Depends(get_db)):
    revision = db.get(Revision, data.source_revision_id)
    if revision is None:
        raise HTTPException(404, detail={"error": "source_revision_not_found"})
    if revision.status != "active":
        raise HTTPException(422, detail={"error": "source_revision_not_active"})
    evidence = None
    if data.source_evidence_id:
        evidence = db.get(RevisionEvidence, data.source_evidence_id)
        if evidence is None or evidence.revision_id != revision.id:
            raise HTTPException(422, detail={"error": "source_evidence_mismatch"})
        if evidence.decision != "approved" or evidence.reviewed_content_hash != revision.content_hash:
            raise HTTPException(422, detail={"error": "source_evidence_not_currently_approved"})
    delta = CanonDelta(chapter_id=revision.chapter_id, source_revision_id=revision.id,
                       source_evidence_id=evidence.id if evidence else None, fact_key=data.fact_key,
                       fact_payload=dict(data.fact_payload), status="proposed", proposed_by_role="author",
                       proposed_by_user_id=user.id)
    db.add(delta)
    db.commit()
    db.refresh(delta)
    return _delta_json(delta)


@router.get("/chapters/{chapter_id}/canon-deltas")
def list_deltas(chapter_id: str, identity=Depends(require_canon_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(CanonDelta).where(CanonDelta.chapter_id == chapter_id).order_by(CanonDelta.proposed_at)).all()
    return [_delta_json(row) for row in rows]


@router.get("/chapters/{chapter_id}/canon")
def list_canon(chapter_id: str, identity=Depends(require_canon_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(Canon).where(Canon.chapter_id == chapter_id, Canon.rolled_back_at.is_(None)).order_by(Canon.accepted_at)).all()
    return [_canon_json(row) for row in rows]


def _decide(delta_id: str, decision: str, reason: str | None, user: User, db: Session):
    delta = db.get(CanonDelta, delta_id)
    if delta is None:
        raise HTTPException(404, detail={"error": "canon_delta_not_found"})
    if delta.status != "proposed":
        raise HTTPException(422, detail={"error": "delta_not_proposed"})
    evidence_ids = [delta.source_evidence_id] if delta.source_evidence_id else []
    receipt = AcceptanceReceipt(delta_id=delta.id, decision=decision, reviewer_user_id=user.id,
                                reason=reason, criteria_snapshot=dict(delta.fact_payload),
                                source_revision_ids=[delta.source_revision_id], source_evidence_ids=evidence_ids)
    db.add(receipt)
    if decision == "accepted":
        existing = db.scalar(select(Canon).where(Canon.chapter_id == delta.chapter_id,
                                                  Canon.fact_key == delta.fact_key,
                                                  Canon.rolled_back_at.is_(None)))
        now = datetime.now(UTC)
        if existing is not None:
            existing.rolled_back_at = now
            old_delta = db.get(CanonDelta, existing.active_delta_id)
            if old_delta is not None:
                old_delta.status = "superseded"
                old_delta.superseded_by_delta_id = delta.id
        db.add(Canon(chapter_id=delta.chapter_id, active_delta_id=delta.id, fact_key=delta.fact_key,
                     fact_payload=dict(delta.fact_payload), accepted_by_user_id=user.id, accepted_at=now))
    delta.status = decision
    db.commit()
    db.refresh(receipt)
    return {"delta": _delta_json(delta), "receipt_id": receipt.id}


@router.post("/canon-deltas/{delta_id}/accept")
def accept_delta(delta_id: str, data: DecisionBody | None = None, user: User = Depends(require_canon_author), db: Session = Depends(get_db)):
    return _decide(delta_id, "accepted", data.reason if data else None, user, db)


@router.post("/canon-deltas/{delta_id}/reject")
def reject_delta(delta_id: str, data: DecisionBody | None = None, user: User = Depends(require_canon_author), db: Session = Depends(get_db)):
    return _decide(delta_id, "rejected", data.reason if data else None, user, db)


@router.post("/chapters/{chapter_id}/rollback")
def rollback(chapter_id: str, data: RollbackBody, user: User = Depends(require_canon_author), db: Session = Depends(get_db)):
    if bool(data.target_log_id) == bool(data.target_timestamp):
        raise HTTPException(422, detail={"error": "rollback_target_required"})
    logs = db.scalars(select(RevisionPublishLog).where(RevisionPublishLog.chapter_id == chapter_id).order_by(RevisionPublishLog.published_at)).all()
    if data.target_log_id:
        target = next((log for log in logs if log.id == data.target_log_id), None)
        if target is None:
            raise HTTPException(404, detail={"error": "target_log_not_found"})
        cutoff = target.published_at
    else:
        cutoff = data.target_timestamp.replace(tzinfo=None) if data.target_timestamp and data.target_timestamp.tzinfo else data.target_timestamp
    recent_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=60)
    if db.scalar(select(RollbackReceipt).where(RollbackReceipt.chapter_id == chapter_id, RollbackReceipt.rolled_back_at >= recent_cutoff)):
        raise HTTPException(409, detail={"error": "rollback_already_recorded_recently"})
    affected_logs = [log for log in logs if log.published_at > cutoff]
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(404, detail={"error": "chapter_not_found"})
    # Clear the current active row before assigning the prior one; this
    # ordering is required by the chapter partial unique index on SQLite.
    for log in reversed(affected_logs):
        new_revision = db.get(Revision, log.new_active_revision_id)
        if new_revision is not None:
            new_revision.status = "archived"
    db.flush()
    for log in reversed(affected_logs):
        old_revision = db.get(Revision, log.old_active_revision_id) if log.old_active_revision_id else None
        if old_revision is not None:
            old_revision.status = "active"
            chapter.content = old_revision.content
    now = datetime.now(UTC)
    canon_rows = db.scalars(select(Canon).where(Canon.chapter_id == chapter_id, Canon.accepted_at > cutoff, Canon.rolled_back_at.is_(None))).all()
    affected_canon_ids = []
    for row in canon_rows:
        row.rolled_back_at = now
        affected_canon_ids.append(row.id)
        previous = db.scalar(select(Canon).where(Canon.chapter_id == chapter_id, Canon.fact_key == row.fact_key,
                                               Canon.rolled_back_at.is_not(None), Canon.accepted_at <= cutoff).order_by(Canon.accepted_at.desc()))
        if previous is not None:
            previous.rolled_back_at = None
            previous_delta = db.get(CanonDelta, previous.active_delta_id)
            if previous_delta is not None:
                previous_delta.status = "accepted"
    receipts = db.scalars(select(AcceptanceReceipt).join(CanonDelta, AcceptanceReceipt.delta_id == CanonDelta.id)
                          .where(CanonDelta.chapter_id == chapter_id, AcceptanceReceipt.reviewed_at > cutoff)).all()
    affected_receipt_ids = [receipt.id for receipt in receipts]
    receipt = RollbackReceipt(chapter_id=chapter_id, target_log_id=data.target_log_id, target_timestamp=None if data.target_log_id else data.target_timestamp,
                              rolled_back_by_user_id=user.id, reason=data.reason,
                              affected_publish_log_ids=[log.id for log in affected_logs], affected_canon_ids=affected_canon_ids,
                              affected_receipt_ids=affected_receipt_ids)
    db.add(receipt)
    db.commit()
    return {"rollback_receipt_id": receipt.id, "active_revision_id": next((log.old_active_revision_id for log in reversed(affected_logs) if log.old_active_revision_id), None),
            "affected_publish_log_ids": receipt.affected_publish_log_ids, "affected_canon_ids": receipt.affected_canon_ids,
            "affected_receipt_ids": receipt.affected_receipt_ids}


@router.get("/chapters/{chapter_id}/rollback-receipts")
def list_rollback_receipts(chapter_id: str, identity=Depends(require_canon_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(RollbackReceipt).where(RollbackReceipt.chapter_id == chapter_id).order_by(RollbackReceipt.rolled_back_at)).all()
    return [{"id": row.id, "chapter_id": row.chapter_id, "target_log_id": row.target_log_id, "target_timestamp": row.target_timestamp.isoformat() if row.target_timestamp else None,
             "rolled_back_by_user_id": row.rolled_back_by_user_id, "reason": row.reason, "rolled_back_at": row.rolled_back_at.isoformat(),
             "affected_publish_log_ids": row.affected_publish_log_ids, "affected_canon_ids": row.affected_canon_ids,
             "affected_receipt_ids": row.affected_receipt_ids} for row in rows]
