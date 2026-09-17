"""Persistent organization settings.

Revision ID: 0008_organization
Revises: 0007_work_merges
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_organization"
down_revision = "0007_work_merges"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM organization_settings)")):
        raise RuntimeError(
            "Organization settings cannot be preserved by the older schema. "
            "Restore a pre-upgrade backup."
        )
    op.drop_table("organization_settings")
