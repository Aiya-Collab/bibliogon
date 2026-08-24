"""Reference-anchor resolution for the novel project tree."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Reference


def _paragraph_index(text: str, offset: int) -> int:
    return text[:offset].count("\n")


def resolve_reference(reference: Reference, content: str) -> Reference:
    """Resolve a C-0.3 anchor and persist its three-state result."""
    exact = reference.anchor_before + reference.anchor_at + reference.anchor_after
    def find_positions(needle: str, offset: int = 0) -> list[int]:
        positions: list[int] = []
        start = 0
        while needle:
            pos = content.find(needle, start)
            if pos < 0:
                break
            positions.append(pos + offset)
            start = pos + 1
        return positions

    # C-0.3 is deliberately two-pass: use the complete three-part anchor
    # first, and only relax to anchor_at when the exact sequence disappeared.
    positions = find_positions(exact, len(reference.anchor_before)) if exact else []
    if not positions:
        positions = find_positions(reference.anchor_at)
    now = datetime.now(UTC)
    reference.last_checked_at = now
    reference.candidate_positions = None
    if len(positions) == 1:
        reference.para_index = _paragraph_index(content, positions[0])
        reference.status = "valid"
        reference.last_resolved_at = now
    elif len(positions) > 1:
        reference.status = "needs_relocate"
        reference.candidate_positions = json.dumps(positions)
    else:
        reference.status = "broken"
    return reference


def resolve_chapter_references(db: Session, chapter_id: str, content: str) -> int:
    rows = db.query(Reference).filter(Reference.chapter_id == chapter_id).all()
    for row in rows:
        resolve_reference(row, content)
    if rows:
        db.commit()
    return len(rows)
