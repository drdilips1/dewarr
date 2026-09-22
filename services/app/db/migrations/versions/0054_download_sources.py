"""Remember download folders chosen in settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_download_sources"
down_revision = "0053_oidc_group_scope"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "import_storage_settings",
        sa.Column(
            "sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM import_storage_settings WHERE sources <> '{}'::jsonb)"
        )
    ):
        raise RuntimeError(
            "Restore a pre-upgrade backup rather than discarding saved download folders"
        )
    op.drop_column("import_storage_settings", "sources")
