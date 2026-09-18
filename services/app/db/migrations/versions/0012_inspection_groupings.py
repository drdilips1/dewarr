"""Immutable file-group review history.

Revision ID: 0012_groupings
Revises: 0011_import_runs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_groupings"
down_revision = "0011_import_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inspection_groupings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("previous_revision", sa.String(64), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("inspection_id", "position"),
    )
    op.create_index(
        "ix_inspection_groupings_inspection_id", "inspection_groupings", ["inspection_id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM inspection_groupings)")):
        raise RuntimeError("File-group review history requires a pre-upgrade backup for rollback")
    op.drop_table("inspection_groupings")
