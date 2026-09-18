"""Initial cover preparation and export evidence.

Revision ID: 0013_import_covers
Revises: 0012_groupings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_import_covers"
down_revision = "0012_groupings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("import_entries", sa.Column("cover_export", postgresql.JSONB()))


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM import_entries WHERE cover_export IS NOT NULL)")
    ):
        raise RuntimeError("Cover export history requires a pre-upgrade backup for rollback")
    op.drop_column("import_entries", "cover_export")
