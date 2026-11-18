"""Immutable per-job resume reviews and approved exports."""
from alembic import op
import sqlalchemy as sa
revision = "0006"
down_revision = "0005"

def upgrade():
    op.create_table("resume_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(200), sa.ForeignKey("jobs.job_id"), nullable=False),
        sa.Column("master_id", sa.String(64), sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("master_text", sa.Text(), nullable=False),
        sa.Column("job_fingerprint", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("pdf", sa.LargeBinary()), sa.Column("docx", sa.LargeBinary()),
        sa.Column("pdf_sha256", sa.String(64)), sa.Column("docx_sha256", sa.String(64)),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'superseded')", name="valid_proposal_status"))
    op.create_index("ix_resume_proposals_job_id", "resume_proposals", ["job_id"])

def downgrade():
    raise RuntimeError("Restore a backup to preserve resume approval history")
