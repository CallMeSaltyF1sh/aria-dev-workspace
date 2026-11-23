"""Initial local asset and media job index."""
from alembic import op
from devworkspace.storage import metadata

revision = "001"
down_revision = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())
