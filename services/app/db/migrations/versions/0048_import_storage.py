"""Persist library folders selected in settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_import_storage"
down_revision = "0047_discovery_collections"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "import_storage_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("destinations", postgresql.JSONB(), nullable=False),
        sa.Column("staging_root", sa.String(1024)),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM import_storage_settings)")):
        raise RuntimeError(
            "Restore a pre-upgrade backup rather than discarding saved library mounts"
        )
    op.drop_table("import_storage_settings")
