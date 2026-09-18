"""Authorized transfer joins and immutable later import continuations."""

import sqlalchemy as sa
from alembic import op

revision = "0037_download_joins"
down_revision = "0036_download_memberships"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "download_memberships",
        sa.Column("join_operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
    )
    op.create_table(
        "automatic_import_continuations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("download_attempts.id"), nullable=False),
        sa.Column(
            "join_operation_id",
            sa.Uuid(),
            sa.ForeignKey("operations.id"),
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
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id")),
        sa.Column("import_run_id", sa.Uuid(), sa.ForeignKey("import_runs.id"), unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("evidence", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("state IN ('queued', 'inspecting', 'held', 'importing', 'complete')"),
    )
    op.create_index(
        "ix_automatic_import_continuations_attempt_id",
        "automatic_import_continuations",
        ["attempt_id"],
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM download_memberships "
            "WHERE join_operation_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM automatic_import_continuations)"
        )
    ):
        raise RuntimeError("Transfer joins and later import history require a pre-upgrade backup")
    op.drop_table("automatic_import_continuations")
    op.drop_column("download_memberships", "join_operation_id")
