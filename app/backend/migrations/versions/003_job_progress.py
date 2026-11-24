"""Persist progress for whole-recording extraction."""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("progress", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("jobs", "progress")
