"""Reviewed connection repairs preserve frozen selections and submission history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_repairs"
down_revision = "0019_fulfillment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "download_repairs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("download_attempts.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("actor_id", "command_key"),
        sa.UniqueConstraint("operation_id"),
        sa.CheckConstraint("state IN ('pending', 'applied', 'held')"),
    )
    op.create_index("ix_download_repairs_attempt_id", "download_repairs", ["attempt_id"])
    op.create_index(
        "uq_pending_download_repair",
        "download_repairs",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM download_repairs)")):
        raise RuntimeError("Download repair history requires a pre-upgrade backup for rollback")
    op.drop_table("download_repairs")
