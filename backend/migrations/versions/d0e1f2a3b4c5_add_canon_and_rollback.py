"""add canon decisions and rollback receipts"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canon_delta",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_revision_id", sa.String(32), sa.ForeignKey("revision_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_evidence_id", sa.String(32), sa.ForeignKey("revision_evidence.id")),
        sa.Column("fact_key", sa.String(200), nullable=False),
        sa.Column("fact_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("proposed_by_role", sa.String(16), nullable=False),
        sa.Column("proposed_by_user_id", sa.String(32), sa.ForeignKey("users.id")),
        sa.Column("ai_run_id", sa.String(32), sa.ForeignKey("ai_runs.id")),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by_delta_id", sa.String(32), sa.ForeignKey("canon_delta.id")),
    )
    op.create_index("ix_canon_delta_chapter_id", "canon_delta", ["chapter_id"])
    op.create_index("ix_canon_delta_fact_key", "canon_delta", ["fact_key"])
    op.create_index("ix_canon_delta_status", "canon_delta", ["status"])
    op.create_table(
        "canon",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active_delta_id", sa.String(32), sa.ForeignKey("canon_delta.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("fact_key", sa.String(200), nullable=False),
        sa.Column("fact_payload", sa.JSON(), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_canon_chapter_id", "canon", ["chapter_id"])
    op.create_index("uq_canon_active_fact", "canon", ["chapter_id", "fact_key"], unique=True, sqlite_where=sa.text("rolled_back_at IS NULL"))
    op.create_table(
        "acceptance_receipt",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("delta_id", sa.String(32), sa.ForeignKey("canon_delta.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("criteria_snapshot", sa.JSON()),
        sa.Column("source_revision_ids", sa.JSON(), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_acceptance_delta_decision", "acceptance_receipt", ["delta_id", "decision"], unique=True)
    op.create_table(
        "rollback_receipt",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_log_id", sa.String(32), sa.ForeignKey("revision_publish_log.id")),
        sa.Column("target_timestamp", sa.DateTime(timezone=True)),
        sa.Column("rolled_back_by_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("affected_publish_log_ids", sa.JSON(), nullable=False),
        sa.Column("affected_canon_ids", sa.JSON(), nullable=False),
        sa.Column("affected_receipt_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rollback_receipt_chapter_id", "rollback_receipt", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_rollback_receipt_chapter_id", table_name="rollback_receipt")
    op.drop_table("rollback_receipt")
    op.drop_index("uq_acceptance_delta_decision", table_name="acceptance_receipt")
    op.drop_table("acceptance_receipt")
    op.drop_index("uq_canon_active_fact", table_name="canon")
    op.drop_index("ix_canon_chapter_id", table_name="canon")
    op.drop_table("canon")
    op.drop_index("ix_canon_delta_status", table_name="canon_delta")
    op.drop_index("ix_canon_delta_fact_key", table_name="canon_delta")
    op.drop_index("ix_canon_delta_chapter_id", table_name="canon_delta")
    op.drop_table("canon_delta")
