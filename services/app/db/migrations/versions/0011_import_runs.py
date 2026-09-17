"""Durable per-version publication reservations and confirmation state.

Revision ID: 0011_import_runs
Revises: 0010_destinations
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_import_runs"
down_revision = "0010_destinations"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade():
    op.create_table(
        "import_runs",
        *identity(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("frozen_import_plans.id"), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("owner_id", "command_key"),
    )
    op.create_index("ix_import_runs_owner_id", "import_runs", ["owner_id"])
    op.create_table(
        "import_entries",
        *identity(),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("import_runs.id"), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("versions.id"), nullable=False),
        sa.Column("destination_id", sa.Uuid(), sa.ForeignKey("import_destinations.id")),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), unique=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("reserved", sa.Boolean(), nullable=False),
        sa.Column("specification", postgresql.JSONB()),
        sa.Column("configuration", postgresql.JSONB()),
        sa.Column("expected_metadata", postgresql.JSONB()),
        sa.Column("receipt", postgresql.JSONB()),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("library_assets.id")),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "group_id"),
        sa.CheckConstraint(
            "state IN ('queued', 'publishing', 'awaiting-library', 'confirmed', 'held', 'skipped')"
        ),
    )
    op.create_index("ix_import_entries_run_id", "import_entries", ["run_id"])
    op.create_index("ix_import_entries_next_check_at", "import_entries", ["next_check_at"])
    op.create_index(
        "uq_import_reserved_version",
        "import_entries",
        ["destination_id", "version_id"],
        unique=True,
        postgresql_where=sa.text("reserved"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM import_runs)")):
        raise RuntimeError("Published import history requires a pre-upgrade backup for rollback")
    op.drop_table("import_entries")
    op.drop_table("import_runs")
