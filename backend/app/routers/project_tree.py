"""Card C project trees, outline generation/rebuild, and text anchors."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Book, Chapter, ProjectNode, ProjectNodeReference, Reference
from app.services.project_references import resolve_chapter_references

router = APIRouter(prefix="/books/{book_id}/project-tree", tags=["project-tree"])
references_router = APIRouter(prefix="/references", tags=["project-tree"])

TREE_RULES = {
    "manuscript": {"volume": (None,), "part": ("volume",), "chapter": ("part",), "scene": ("chapter",)},
    "story_bible": {"grouping": (None, "grouping")},
    "plot": {"act": (None,), "beat": ("act",), "beat_detail": ("beat",)},
    "research": {"note": (None, "note")},
    "archive": {"item": (None, "item")},
}


class NodeIn(BaseModel):
    tree_type: Literal["manuscript", "story_bible", "plot", "research", "archive"]
    node_type: str
    title: str = Field(min_length=1, max_length=500)
    parent_id: str | None = None
    position: int | None = None
    ref_chapter_id: str | None = None
    ref_target_json: dict[str, Any] | None = None
    status: Literal["active", "draft_placeholder", "needs_review"] = "active"


class NodePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    position: int | None = None
    status: Literal["active", "draft_placeholder", "needs_review"] | None = None
    ref_target_json: dict[str, Any] | None = None


class ReferenceIn(BaseModel):
    chapter_id: str
    anchor_before: str = Field(max_length=60)
    anchor_at: str = Field(min_length=1, max_length=60)
    anchor_after: str = Field(max_length=60)
    para_index: int = Field(ge=0)


class MoveIn(BaseModel):
    parent_id: str | None
    position: int = Field(ge=0)


class RebuildNodeIn(BaseModel):
    node_type: Literal["volume", "part", "chapter", "scene"]
    title: str = Field(min_length=1, max_length=500)
    parent_index: int | None = None
    ref_chapter_id: str | None = None
    replace_node_id: str | None = None
    status: Literal["active", "draft_placeholder", "needs_review"] = "active"


class RebuildApplyIn(BaseModel):
    nodes: list[RebuildNodeIn]


def _book(book_id: str, db: Session) -> None:
    if not db.query(Book.id).filter(Book.id == book_id).first():
        raise HTTPException(404, "Book not found")


def _node(book_id: str, node_id: str, db: Session) -> ProjectNode:
    row = db.query(ProjectNode).filter(ProjectNode.id == node_id, ProjectNode.book_id == book_id).first()
    if not row:
        raise HTTPException(404, "Project node not found")
    return row


def _validate_node(book_id: str, data: NodeIn, db: Session) -> None:
    allowed = TREE_RULES[data.tree_type]
    if data.node_type not in allowed:
        raise HTTPException(422, "node_type is not allowed for this tree")
    parent_type = None
    if data.parent_id:
        parent = _node(book_id, data.parent_id, db)
        if parent.tree_type != data.tree_type:
            raise HTTPException(422, "parent must be in the same tree")
        parent_type = parent.node_type
    if parent_type not in allowed[data.node_type]:
        raise HTTPException(422, "invalid parent for node_type")
    if data.node_type == "chapter":
        if not data.ref_chapter_id:
            raise HTTPException(422, "manuscript chapter requires ref_chapter_id")
        if not db.query(Chapter.id).filter(Chapter.id == data.ref_chapter_id, Chapter.book_id == book_id).first():
            raise HTTPException(422, "ref_chapter_id must belong to this book")
    elif data.ref_chapter_id:
        raise HTTPException(422, "only manuscript chapter may set ref_chapter_id")


def _out(row: ProjectNode) -> dict[str, Any]:
    return {"id": row.id, "book_id": row.book_id, "tree_type": row.tree_type, "parent_id": row.parent_id,
            "node_type": row.node_type, "title": row.title, "position": row.position,
            "ref_chapter_id": row.ref_chapter_id, "ref_target_json": json.loads(row.ref_target_json) if row.ref_target_json else None,
            "status": row.status}


@router.get("")
def list_nodes(book_id: str, tree_type: str | None = None, node_type: str | None = None, status_value: str | None = Query(None, alias="status"), keyword: str | None = None, ref_chapter_id: str | None = None, limit: int = Query(100, le=200), offset: int = 0, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _book(book_id, db)
    q = db.query(ProjectNode).filter(ProjectNode.book_id == book_id)
    for col, value in ((ProjectNode.tree_type, tree_type), (ProjectNode.node_type, node_type), (ProjectNode.status, status_value), (ProjectNode.ref_chapter_id, ref_chapter_id)):
        if value is not None: q = q.filter(col == value)
    if keyword: q = q.filter(ProjectNode.title.ilike(f"%{keyword}%"))
    return [_out(row) for row in q.order_by(ProjectNode.position, ProjectNode.created_at).offset(offset).limit(limit)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_node(book_id: str, data: NodeIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _book(book_id, db); _validate_node(book_id, data, db)
    position = data.position if data.position is not None else (db.query(ProjectNode).filter(ProjectNode.book_id == book_id, ProjectNode.parent_id == data.parent_id).count())
    row = ProjectNode(book_id=book_id, **data.model_dump(exclude={"ref_target_json", "position"}), position=position, ref_target_json=json.dumps(data.ref_target_json) if data.ref_target_json else None)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(422, "ref_chapter_id is already linked in manuscript") from exc
    db.refresh(row)
    return _out(row)


@router.patch("/{node_id}")
def patch_node(book_id: str, node_id: str, data: NodePatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _node(book_id, node_id, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, json.dumps(value) if key == "ref_target_json" and value is not None else value)
    db.commit(); db.refresh(row); return _out(row)


@router.post("/{node_id}/move")
def move_node(book_id: str, node_id: str, data: MoveIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _node(book_id, node_id, db)
    parent = _node(book_id, data.parent_id, db) if data.parent_id else None
    if parent and parent.tree_type != row.tree_type:
        raise HTTPException(422, "parent must be in the same tree")
    expected = TREE_RULES[row.tree_type][row.node_type]
    if (parent.node_type if parent else None) not in expected:
        raise HTTPException(422, "invalid parent for node_type")
    if parent and parent.id == row.id:
        raise HTTPException(422, "node cannot parent itself")
    row.parent_id = data.parent_id
    siblings = db.query(ProjectNode).filter(ProjectNode.book_id == book_id, ProjectNode.parent_id == data.parent_id, ProjectNode.id != row.id).order_by(ProjectNode.position).all()
    siblings.insert(min(data.position, len(siblings)), row)
    for position, sibling in enumerate(siblings): sibling.position = position
    db.commit(); db.refresh(row); return _out(row)


@router.delete("/{node_id}", status_code=204)
def delete_node(book_id: str, node_id: str, db: Session = Depends(get_db)) -> None:
    db.delete(_node(book_id, node_id, db)); db.commit()


@router.post("/{source_node_id}/references", status_code=201)
def create_cross_reference(book_id: str, source_node_id: str, target_node_id: str, kind: str, db: Session = Depends(get_db)) -> dict[str, str]:
    _node(book_id, source_node_id, db); _node(book_id, target_node_id, db)
    row = ProjectNodeReference(source_node_id=source_node_id, target_node_id=target_node_id, kind=kind); db.add(row); db.commit(); return {"id": row.id}


@router.get("/outline/generate")
def generate_outline(book_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(ProjectNode).filter(ProjectNode.book_id == book_id, ProjectNode.tree_type == "manuscript").order_by(ProjectNode.position).all()
    children: dict[str | None, list[ProjectNode]] = defaultdict(list)
    for row in rows: children[row.parent_id].append(row)
    def build(parent: str | None) -> list[dict[str, Any]]:
        return [{**_out(row), "children": build(row.id)} for row in children[parent]]
    return build(None)


@router.post("/rebuild")
def rebuild_suggestions(book_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _book(book_id, db); result: list[dict[str, Any]] = []; seen: set[int] = set()
    for chapter in db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.position):
        try: document = json.loads(chapter.content)
        except (TypeError, ValueError): continue
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "heading" and node.get("attrs", {}).get("level") in (1,2,3,4):
                    level = node["attrs"]["level"]
                    for missing in range(1, level):
                        if missing not in seen: result.append({"node_type": ("volume","part","chapter")[missing-1], "title": "（未命名部）", "status": "draft_placeholder", "level": missing}); seen.add(missing)
                    text = "".join(c.get("text", "") for c in node.get("content", []) if isinstance(c, dict)) or "(空标题)"
                    result.append({"node_type": ("volume","part","chapter","scene")[level-1], "title": text, "status": "active", "level": level, "ref_chapter_id": chapter.id if level == 3 else None}); seen.add(level)
                for child in node.get("content", []) or []: walk(child)
        walk(document)
    return result


@router.post("/rebuild-apply", status_code=201)
def rebuild_apply(book_id: str, data: RebuildApplyIn, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Author-confirmed rebuild only; creates history unless explicitly replaced."""
    _book(book_id, db)
    created: list[ProjectNode] = []
    try:
        # The book existence lookup may already have opened SQLAlchemy's
        # implicit transaction; a savepoint keeps this confirmation atomic.
        with db.begin_nested():
            for item in data.nodes:
                parent_id = created[item.parent_index].id if item.parent_index is not None else None
                proposed = NodeIn(tree_type="manuscript", node_type=item.node_type, title=item.title,
                                  parent_id=parent_id, ref_chapter_id=item.ref_chapter_id, status=item.status)
                _validate_node(book_id, proposed, db)
                if item.replace_node_id:
                    row = _node(book_id, item.replace_node_id, db)
                    if row.tree_type != "manuscript": raise HTTPException(422, "replace_node_id must be manuscript")
                    row.node_type, row.title, row.parent_id, row.ref_chapter_id, row.status = item.node_type, item.title, parent_id, item.ref_chapter_id, item.status
                else:
                    row = ProjectNode(book_id=book_id, tree_type="manuscript", node_type=item.node_type, title=item.title,
                                      parent_id=parent_id, ref_chapter_id=item.ref_chapter_id, status=item.status,
                                      position=db.query(ProjectNode).filter(ProjectNode.book_id == book_id, ProjectNode.parent_id == parent_id).count())
                    db.add(row)
                    db.flush()
                created.append(row)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return [_out(row) for row in created]


@references_router.post("/scene/{heading_node_id}", status_code=201)
def create_reference(heading_node_id: str, data: ReferenceIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = db.query(ProjectNode).filter(ProjectNode.id == heading_node_id, ProjectNode.node_type == "scene").first()
    if not node: raise HTTPException(422, "heading_node_id must be a scene")
    row = Reference(heading_node_id=heading_node_id, **data.model_dump()); db.add(row); db.commit(); return {"id": row.id, "status": row.status}


@references_router.post("/resolve")
def resolve_references(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, int]:
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter: raise HTTPException(404, "Chapter not found")
    return {"resolved": resolve_chapter_references(db, chapter_id, chapter.content)}


@references_router.get("")
def list_references(book_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(Reference, ProjectNode).join(ProjectNode, Reference.heading_node_id == ProjectNode.id).filter(ProjectNode.book_id == book_id).all()
    return [{"id": ref.id, "heading_node_id": ref.heading_node_id, "chapter_id": ref.chapter_id,
             "para_index": ref.para_index, "status": ref.status, "candidate_positions": json.loads(ref.candidate_positions) if ref.candidate_positions else []}
            for ref, _node_row in rows]
