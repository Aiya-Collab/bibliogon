"""add distillation runs and staging artifacts"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
revision = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("distillation_run", sa.Column("id", sa.String(32), primary_key=True), sa.Column("book_id", sa.String(32), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False), sa.Column("source_format", sa.String(16), nullable=False), sa.Column("source_filename", sa.String(512), nullable=False), sa.Column("source_hash", sa.String(64), nullable=False), sa.Column("total_chars", sa.Integer, nullable=False), sa.Column("total_chapters", sa.Integer, nullable=False), sa.Column("provider_used", sa.String(32), nullable=False), sa.Column("model_used", sa.String(100), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("error_message", sa.Text), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("result_counts", sa.JSON), sa.Column("prompt_hash", sa.String(64), nullable=False), sa.Column("response_hash", sa.String(64), nullable=False))
    op.create_index("ix_distillation_run_book_id", "distillation_run", ["book_id"]); op.create_index("ix_distillation_run_user_id", "distillation_run", ["user_id"]); op.create_index("ix_distillation_run_status", "distillation_run", ["status"])
    op.create_table("distillation_artifact", sa.Column("id", sa.String(32), primary_key=True), sa.Column("run_id", sa.String(32), sa.ForeignKey("distillation_run.id", ondelete="CASCADE"), nullable=False), sa.Column("book_id", sa.String(32), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False), sa.Column("artifact_type", sa.String(32), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("payload", sa.JSON, nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("distillation_source", sa.String(16), nullable=False), sa.Column("created_by_role", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_distillation_artifact_run_id", "distillation_artifact", ["run_id"]); op.create_index("ix_distillation_artifact_book_id", "distillation_artifact", ["book_id"])

def downgrade():
    op.drop_index("ix_distillation_artifact_book_id", table_name="distillation_artifact"); op.drop_index("ix_distillation_artifact_run_id", table_name="distillation_artifact"); op.drop_table("distillation_artifact")
    op.drop_index("ix_distillation_run_status", table_name="distillation_run"); op.drop_index("ix_distillation_run_user_id", table_name="distillation_run"); op.drop_index("ix_distillation_run_book_id", table_name="distillation_run"); op.drop_table("distillation_run")
