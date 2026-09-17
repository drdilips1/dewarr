"""Durable read-only inspections and frozen import plans.

Revision ID: 0009_import_plans
Revises: 0008_organization
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_import_plans"
down_revision = "0008_organization"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "download_inspections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False, unique=True
        ),
        sa.Column("source_key", sa.String(60), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("snapshot", postgresql.JSONB()),
        sa.CheckConstraint("state IN ('queued', 'running', 'ready', 'failed')"),
    )
    op.create_index("ix_download_inspections_owner_id", "download_inspections", ["owner_id"])
    op.create_table(
        "frozen_import_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id"), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("inspection_id", "revision"),
    )
    op.create_index(
        "ix_frozen_import_plans_inspection_id", "frozen_import_plans", ["inspection_id"]
    )
    op.create_index("ix_frozen_import_plans_owner_id", "frozen_import_plans", ["owner_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM download_inspections)")):
        raise RuntimeError("Inspection history needs a pre-upgrade backup for rollback")
    op.drop_table("frozen_import_plans")
    op.drop_table("download_inspections")
