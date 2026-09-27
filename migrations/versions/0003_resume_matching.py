"""Versioned resumes, assessment history and the 80 percent approval rule."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"


def upgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("auto_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("resume_match_percent", sa.Float()))
        batch.drop_constraint("approval_required", type_="check")
        batch.create_check_constraint("approval_required", "status != 'Approved' OR human_approval = true OR (auto_approved = true AND resume_match_percent IS NOT NULL AND resume_match_percent >= 80)")
    op.create_table("resumes", sa.Column("id", sa.String(64), primary_key=True),
                    sa.Column("filename", sa.Text(), nullable=False), sa.Column("text", sa.Text(), nullable=False))
    op.create_table("resume_assessments", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("job_id", sa.String(200), sa.ForeignKey("jobs.job_id"), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("result", sa.JSON(), nullable=False))
    op.create_index("ix_resume_assessments_job_id", "resume_assessments", ["job_id"])


def downgrade():
    raise RuntimeError("Restore a backup to retain a consistent approval history")
