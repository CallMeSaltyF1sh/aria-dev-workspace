"""Initial local asset and media job index."""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("path", sa.String(), unique=True, nullable=False),
        sa.Column("fingerprint", sa.String()),
        sa.Column("hash", sa.String()),
        sa.Column("device", sa.String()),
        sa.Column("info", sa.JSON(), nullable=False),
        sa.Column("study", sa.JSON(), nullable=False),
        sa.Column("missing", sa.Integer()),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.String()),
    )


def downgrade():
    op.drop_table("jobs")
    op.drop_table("assets")
