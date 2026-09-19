"""Reviewed complete-book contents of one inseparable backend item."""

import sqlalchemy as sa
from alembic import op

revision = "0038_asset_containment"
down_revision = "0037_download_joins"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_assets", sa.Column("containment", sa.dialects.postgresql.JSONB()))


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM library_assets WHERE containment IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM identity_changes WHERE "
            "before->>'containment' IS NOT NULL OR after->>'containment' IS NOT NULL)"
        )
    ):
        raise RuntimeError("Reviewed collection contents require a pre-upgrade backup")
    op.drop_column("library_assets", "containment")
