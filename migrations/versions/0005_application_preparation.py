"""Application preparation and manual submission records, preserving tracker columns."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table("application_preparations",
        sa.Column("job_id", sa.String(200), sa.ForeignKey("jobs.job_id"), primary_key=True),
        sa.Column("resume_id", sa.String(64), sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("verified_facts", sa.JSON(), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("submitted_on", sa.Date()),
        sa.Column("channel", sa.String(100)),
        sa.Column("reference", sa.Text()),
        sa.Column("submission_snapshot", sa.JSON()),
        sa.Column("follow_up_on", sa.Date()),
        sa.Column("follow_up_done", sa.Boolean(), nullable=False))
    op.create_index("ix_application_preparations_follow_up_on", "application_preparations", ["follow_up_on"])


def downgrade():
    raise RuntimeError("Restore a backup to preserve application history")
