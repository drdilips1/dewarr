"""Configured library destinations and capability probes.

Revision ID: 0010_destinations
Revises: 0009_import_plans
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_destinations"
down_revision = "0009_import_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_destinations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("root_key", sa.String(60), unique=True, nullable=False),
        sa.Column("library_id", sa.Uuid(), sa.ForeignKey("libraries.id"), nullable=False),
        sa.Column("medium", sa.String(10), nullable=False),
        sa.Column("backend_path", sa.String(1024), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("probe", postgresql.JSONB()),
        sa.Column("probe_operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
        sa.Column("probe_token", sa.Uuid()),
        sa.CheckConstraint("medium IN ('ebook', 'audio')"),
        sa.CheckConstraint("mode IN ('hardlink', 'copy')"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM import_destinations)")):
        raise RuntimeError("Destination configuration needs a pre-upgrade backup for rollback")
    op.drop_table("import_destinations")
