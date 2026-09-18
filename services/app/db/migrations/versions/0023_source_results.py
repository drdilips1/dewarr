"""Private expiring source results, separate from durable inspected artifacts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_source_results"
down_revision = "0022_auto_import"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_key", sa.String(40), sa.ForeignKey("source_connections.key"), nullable=False
        ),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encrypted_reference", sa.Text(), nullable=False),
        sa.Column("release_snapshot", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_source_results_owner_id", "source_results", ["owner_id"])
    op.create_index("ix_source_results_expires_at", "source_results", ["expires_at"])


def downgrade():
    # Results are temporary observations; durable artifacts are retained separately.
    op.drop_table("source_results")
