"""add AI agent run audit log"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_run_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ai_run_id", sa.String(32), sa.ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_role", sa.String(32), nullable=False),
        sa.Column("chapter_id", sa.String(32), sa.ForeignKey("chapters.id", ondelete="SET NULL")),
        sa.Column("prompt_payload_hash", sa.String(64), nullable=False),
        sa.Column("response_payload_hash", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer),
        sa.Column("completion_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("provider_config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_run_log_ai_run_id", "ai_run_log", ["ai_run_id"])
    op.create_index("ix_ai_run_log_agent_role", "ai_run_log", ["agent_role"])
    op.create_index("ix_ai_run_log_chapter_id", "ai_run_log", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_run_log_chapter_id", table_name="ai_run_log")
    op.drop_index("ix_ai_run_log_agent_role", table_name="ai_run_log")
    op.drop_index("ix_ai_run_log_ai_run_id", table_name="ai_run_log")
    op.drop_table("ai_run_log")
