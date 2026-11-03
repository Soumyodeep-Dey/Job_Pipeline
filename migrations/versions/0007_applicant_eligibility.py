"""Confirmed applicant answers and reviewed eligibility conditions."""
from alembic import op
import sqlalchemy as sa
revision = "0007"
down_revision = "0006"
def upgrade():
    op.create_table("applicant_profiles", sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("version",sa.Integer(),nullable=False),sa.Column("data",sa.JSON(),nullable=False),
        sa.Column("confirmed_at",sa.DateTime(timezone=True),nullable=False),sa.Column("confirmed_by",sa.Text(),nullable=False))
    op.create_table("applicant_profile_history",sa.Column("version",sa.Integer(),primary_key=True),
        sa.Column("data",sa.JSON(),nullable=False),sa.Column("confirmed_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("confirmed_by",sa.Text(),nullable=False))
    op.create_table("job_requirement_reviews",sa.Column("job_id",sa.String(200),sa.ForeignKey("jobs.job_id"),primary_key=True),
        sa.Column("version",sa.Integer(),nullable=False),sa.Column("data",sa.JSON(),nullable=False),
        sa.Column("source_hash",sa.String(64),nullable=False),sa.Column("reviewed_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("reviewed_by",sa.Text(),nullable=False),sa.Column("history",sa.JSON(),nullable=False))
    op.create_table("eligibility_assessments",sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("job_id",sa.String(200),sa.ForeignKey("jobs.job_id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("result",sa.JSON(),nullable=False))
    op.create_index("ix_eligibility_assessments_job_id","eligibility_assessments",["job_id"])
def downgrade():
    raise RuntimeError("Restore a backup to preserve confirmed applicant history")
