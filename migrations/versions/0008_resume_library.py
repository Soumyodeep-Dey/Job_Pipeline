"""Persist the single active resume and excluded fingerprints."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"

def upgrade():
    op.create_table("resume_library", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("active_id", sa.String(64), sa.ForeignKey("resumes.id")),
                    sa.Column("removed_ids", sa.JSON(), nullable=False))

def downgrade():
    op.drop_table("resume_library")
