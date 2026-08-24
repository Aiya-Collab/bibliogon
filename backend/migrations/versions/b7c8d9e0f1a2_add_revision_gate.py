"""add users, ai runs, revisions and review evidence"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = ("a6b7c8d9e0f1", "a1b2c3d4e5f7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("username", sa.String(200), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="author"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "revision_revisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parent_revision_id", sa.String(32), sa.ForeignKey("revision_revisions.id")),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("created_by_role", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.String(32), sa.ForeignKey("users.id")),
        sa.Column("ai_run_id", sa.String(32), sa.ForeignKey("ai_runs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by_user_id", sa.String(32), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_revision_revisions_chapter_id", "revision_revisions", ["chapter_id"])
    op.create_index("ix_revision_revisions_status", "revision_revisions", ["status"])
    op.create_index("uq_revision_active_per_chapter", "revision_revisions", ["chapter_id"], unique=True, sqlite_where=sa.text("status = 'active'"))
    op.create_table(
        "revision_evidence",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("revision_id", sa.String(32), sa.ForeignKey("revision_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewed_content_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewer_role", sa.String(16), nullable=False),
        sa.Column("reviewer_user_id", sa.String(32), sa.ForeignKey("users.id")),
        sa.Column("rationale", sa.Text()),
        sa.Column("source_refs", sa.JSON()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "reviewed_content_hash", name="uq_revision_evidence_hash"),
    )
    op.create_table(
        "revision_publish_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("published_by_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("old_active_revision_id", sa.String(32)),
        sa.Column("new_active_revision_id", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.String(32), sa.ForeignKey("revision_evidence.id"), nullable=False),
    )
    op.create_index("ix_revision_publish_log_chapter_id", "revision_publish_log", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_revision_publish_log_chapter_id", table_name="revision_publish_log")
    op.drop_table("revision_publish_log")
    op.drop_table("revision_evidence")
    op.drop_index("uq_revision_active_per_chapter", table_name="revision_revisions")
    op.drop_index("ix_revision_revisions_status", table_name="revision_revisions")
    op.drop_index("ix_revision_revisions_chapter_id", table_name="revision_revisions")
    op.drop_table("revision_revisions")
    op.drop_table("ai_runs")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
