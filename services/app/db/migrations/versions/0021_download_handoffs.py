"""Scoped administrator inspection assignments for completed acquisitions."""

import sqlalchemy as sa
from alembic import op

revision = "0021_handoffs"
down_revision = "0020_repairs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "download_handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("download_attempts.id"), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id"), nullable=False
        ),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("inspection_id"),
        sa.UniqueConstraint("operation_id"),
    )
    op.create_index("ix_download_handoffs_attempt_id", "download_handoffs", ["attempt_id"])
    op.create_index(
        "uq_active_download_handoff",
        "download_handoffs",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM download_handoffs)")):
        raise RuntimeError("Download review history requires a pre-upgrade backup for rollback")
    op.drop_table("download_handoffs")
