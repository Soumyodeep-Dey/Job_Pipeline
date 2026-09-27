"""Bootstrap a fresh database or adopt an existing Phase 1 schema without data loss."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    expected = {
        "companies": {"id", "name", "name_key", "domains", "career_pages", "keyword_profiles"},
        "discovery_config": {"sheet", "keyword_bank", "rules", "notes"},
        "jobs": {"job_id", "company_id", "role", "location", "required_skills", "match_score",
                 "missing_skills", "source_url", "date_found", "status", "resume_version", "human_approval"},
    }
    present = existing & expected.keys()
    if present:
        if present != expected.keys():
            raise RuntimeError("Partial Phase 1 schema detected; restore or repair before migration")
        for table, columns in expected.items():
            if not columns.issubset({column["name"] for column in inspector.get_columns(table)}):
                raise RuntimeError(f"Unexpected existing schema: {table}")
        return
    op.create_table("companies", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False), sa.Column("name_key", sa.Text(), nullable=False, unique=True),
        sa.Column("domains", sa.JSON(), nullable=False), sa.Column("career_pages", sa.JSON(), nullable=False),
        sa.Column("keyword_profiles", sa.JSON(), nullable=False))
    op.create_table("discovery_config", sa.Column("sheet", sa.Text(), primary_key=True),
        sa.Column("keyword_bank", sa.JSON(), nullable=False), sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False))
    op.create_table("jobs", sa.Column("job_id", sa.String(200), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False), sa.Column("location", sa.Text()),
        sa.Column("required_skills", sa.Text()), sa.Column("match_score", sa.Float()),
        sa.Column("missing_skills", sa.Text()), sa.Column("source_url", sa.Text(), unique=True),
        sa.Column("date_found", sa.Date(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("resume_version", sa.Text()), sa.Column("human_approval", sa.Boolean(), nullable=False),
        sa.CheckConstraint("status != 'Approved' OR human_approval = true", name="approval_required"),
        sa.CheckConstraint("match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="score_range"),
        sa.CheckConstraint("length(trim(job_id)) > 0", name="nonempty_job_id"),
        sa.CheckConstraint("source_url IS NULL OR length(trim(source_url)) > 0", name="nonempty_source_url"),
        sa.CheckConstraint("status IN ('New', 'Shortlisted', 'Approved', 'Applied', 'Interview', 'Rejected', 'Offer', 'Withdrawn')", name="valid_status"))
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade():
    raise RuntimeError("Destructive baseline downgrade is disabled; restore a database backup instead")
