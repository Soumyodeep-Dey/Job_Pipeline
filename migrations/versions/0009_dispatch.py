"""Automatic submission control and durable duplicate protection."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"

def upgrade():
    table = op.create_table("dispatch_control", sa.Column("id",sa.Integer,primary_key=True),
                            sa.Column("enabled",sa.Boolean,nullable=False))
    op.bulk_insert(table,[{"id":1,"enabled":False}])
    op.create_table("dispatch_attempts",
        sa.Column("job_id",sa.String(200),sa.ForeignKey("jobs.job_id"),primary_key=True),
        sa.Column("destination",sa.Text,unique=True,nullable=False),
        sa.Column("state",sa.String(32),nullable=False),
        sa.Column("message",sa.Text,nullable=False),
        sa.Column("snapshot",sa.JSON,nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))

def downgrade():
    raise RuntimeError("Restore a backup to preserve application receipts.")
