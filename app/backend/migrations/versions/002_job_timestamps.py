"""Track durable processing order for reload recovery."""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("created_at", sa.String(), nullable=True))


def downgrade():
    op.drop_column("jobs", "created_at")
