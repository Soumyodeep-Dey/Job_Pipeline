"""Daily submission accounting and confirmed answers to employer questions."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"


def upgrade():
    op.add_column("dispatch_attempts", sa.Column("submission_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_dispatch_attempts_submission_started_at", "dispatch_attempts", ["submission_started_at"])
    op.execute("UPDATE dispatch_attempts SET submission_started_at = updated_at WHERE state IN ('sending','received','confirmed','uncertain')")
    op.create_table("form_questions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(200), sa.ForeignKey("jobs.job_id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("spec", sa.JSON, nullable=False),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("profile_version", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_form_questions_job_id", "form_questions", ["job_id"])
    op.create_table("saved_form_answers",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("spec", sa.JSON, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("profile_version", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    raise RuntimeError("Restore a backup to preserve application answers and receipts.")
