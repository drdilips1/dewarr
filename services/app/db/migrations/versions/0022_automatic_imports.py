"""Opt-in automatic import routes and durable per-acquisition continuation."""

import sqlalchemy as sa
from alembic import op

revision = "0022_auto_import"
down_revision = "0021_handoffs"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "automatic_import_policies",
        *identity(),
        sa.Column(
            "destination_id",
            sa.Uuid(),
            sa.ForeignKey("import_destinations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "configuration",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
    )
    op.create_table(
        "automatic_imports",
        *identity(),
        sa.Column(
            "attempt_id",
            sa.Uuid(),
            sa.ForeignKey("download_attempts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "policy_id", sa.Uuid(), sa.ForeignKey("automatic_import_policies.id"), nullable=False
        ),
        sa.Column("policy_generation", sa.Integer(), nullable=False),
        sa.Column(
            "operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False, unique=True
        ),
        sa.Column(
            "inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id"), unique=True
        ),
        sa.Column("import_run_id", sa.Uuid(), sa.ForeignKey("import_runs.id"), unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("evidence", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("state IN ('queued', 'inspecting', 'held', 'importing')"),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM automatic_imports) "
            "OR EXISTS (SELECT 1 FROM automatic_import_policies)"
        )
    ):
        raise RuntimeError(
            "Automatic import authority and history require a pre-upgrade backup for rollback"
        )
    op.drop_table("automatic_imports")
    op.drop_table("automatic_import_policies")
