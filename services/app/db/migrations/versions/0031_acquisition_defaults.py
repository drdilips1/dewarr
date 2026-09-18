"""Sparse installation and personal acquisition preferences."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_acquisition_defaults"
down_revision = "0030_list_policies"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "acquisition_defaults",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), unique=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("preferences", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "(key = 'installation' AND owner_id IS NULL) OR "
            "(owner_id IS NOT NULL AND key = 'user:' || owner_id::text)"
        ),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM acquisition_defaults)")):
        raise RuntimeError("Acquisition defaults require a pre-upgrade backup")
    op.drop_table("acquisition_defaults")
