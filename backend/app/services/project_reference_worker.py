"""Independent daily Reference maintenance worker (Card C-0.3)."""

from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.models import Chapter
from app.services.project_references import resolve_chapter_references

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 24 * 60 * 60


def scan_all_references() -> int:
    with SessionLocal() as db:
        chapters = db.query(Chapter).all()
        return sum(resolve_chapter_references(db, chapter.id, chapter.content) for chapter in chapters)


async def run_daily_reference_scan() -> None:
    """Run once at worker start, then independently every 24 hours."""
    while True:
        try:
            resolved = scan_all_references()
            logger.info("Project reference daily scan resolved %d anchors", resolved)
        except Exception:
            logger.exception("Project reference daily scan failed")
        await asyncio.sleep(INTERVAL_SECONDS)
