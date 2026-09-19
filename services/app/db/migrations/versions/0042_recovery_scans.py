"""Durable read-only observations of external state after restore."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042_recovery_scans"
down_revision = "0041_restore_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recovery_scans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "checkpoint_id", sa.Uuid(), sa.ForeignKey("restore_checkpoints.id"), nullable=False
        ),
        sa.Column(
            "operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False, unique=True
        ),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("context_digest", sa.String(64)),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("state IN ('queued', 'running', 'completed', 'held')"),
    )
    op.create_index("ix_recovery_scans_checkpoint_id", "recovery_scans", ["checkpoint_id"])
    op.create_table(
        "recovery_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "scan_id",
            sa.Uuid(),
            sa.ForeignKey("recovery_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("title", sa.String(600), nullable=False),
        sa.Column("message", sa.String(600), nullable=False),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("scan_id", "position"),
    )
    op.create_index("ix_recovery_findings_scan_id", "recovery_findings", ["scan_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM recovery_scans)")):
        raise RuntimeError("Recovery scan history requires a pre-upgrade backup")
    op.drop_table("recovery_findings")
    op.drop_table("recovery_scans")
