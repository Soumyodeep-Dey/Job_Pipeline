"""Add discovery evidence, run history and candidate settings; preserve tracker fields."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table("matching_profiles", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("settings", sa.JSON(), nullable=False))
    op.create_table("discovery_runs", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False), sa.Column("results", sa.JSON(), nullable=False))
    op.create_table("job_evidence", sa.Column("job_id", sa.String(200), sa.ForeignKey("jobs.job_id"), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_runs.id"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False), sa.Column("board_url", sa.Text(), nullable=False),
        sa.Column("career_page", sa.Text(), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False))
    op.create_index("ix_job_evidence_run_id", "job_evidence", ["run_id"])


def downgrade():
    raise RuntimeError("Discovery history is retained; restore a backup to return to Phase 1")
