"""add novel project trees, cross-tree references, and prose anchors

Revision ID: a6b7c8d9e0f1
Revises: z5d6e7f8a9b0, d5e6f7a8b9c0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = ("z5d6e7f8a9b0", "d5e6f7a8b9c0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("book_id", sa.String(32), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tree_type", sa.String(32), nullable=False),
        sa.Column("parent_id", sa.String(32), sa.ForeignKey("project_nodes.id", ondelete="CASCADE")),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="SET NULL")),
        sa.Column("ref_target_json", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_nodes_book_tree_parent_position", "project_nodes", ["book_id", "tree_type", "parent_id", "position"])
    op.execute("CREATE UNIQUE INDEX uq_project_nodes_manuscript_chapter ON project_nodes (book_id, ref_chapter_id) WHERE tree_type = 'manuscript' AND node_type = 'chapter' AND ref_chapter_id IS NOT NULL")
    op.create_table("project_node_references", sa.Column("id", sa.String(32), primary_key=True), sa.Column("source_node_id", sa.String(32), sa.ForeignKey("project_nodes.id", ondelete="CASCADE"), nullable=False), sa.Column("target_node_id", sa.String(32), sa.ForeignKey("project_nodes.id", ondelete="CASCADE"), nullable=False), sa.Column("kind", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("references", sa.Column("id", sa.String(32), primary_key=True), sa.Column("heading_node_id", sa.String(32), sa.ForeignKey("project_nodes.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False), sa.Column("anchor_before", sa.String(60), nullable=False, server_default=""), sa.Column("anchor_at", sa.String(60), nullable=False, server_default=""), sa.Column("anchor_after", sa.String(60), nullable=False, server_default=""), sa.Column("para_index", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(32), nullable=False, server_default="valid"), sa.Column("candidate_positions", sa.Text()), sa.Column("last_resolved_at", sa.DateTime(timezone=True)), sa.Column("last_checked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_references_chapter_id", "references", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_references_chapter_id", table_name="references")
    op.drop_table("references")
    op.drop_table("project_node_references")
    op.execute("DROP INDEX uq_project_nodes_manuscript_chapter")
    op.drop_index("ix_project_nodes_book_tree_parent_position", table_name="project_nodes")
    op.drop_table("project_nodes")
