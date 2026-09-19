"""Persist the operator-only fence after restoring application state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041_restore_checkpoints"
down_revision = "0040_list_comparisons"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "restore_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("backup_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "uq_restore_checkpoint_active",
        "restore_checkpoints",
        ["active"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM restore_checkpoints)")):
        raise RuntimeError("Restore history requires a pre-upgrade backup")
    op.drop_table("restore_checkpoints")
