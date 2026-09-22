"""Remember books a reader follows until their release day."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0057_monitored_releases"
down_revision = "0056_account_automation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "monitored_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "work_id", sa.Uuid(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("release_date", sa.Date()),
        sa.Column("basis", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("state", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
        sa.Column("specification", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("owner_id", "work_id"),
        sa.CheckConstraint(
            "state IN ('waiting', 'wanted', 'available', 'stopped')",
            name="monitored_release_state",
        ),
        sa.CheckConstraint(
            "basis IN ('audiobook', 'work', 'unknown')",
            name="monitored_release_basis",
        ),
    )
    op.create_index("ix_monitored_releases_owner_id", "monitored_releases", ["owner_id"])
    op.create_index("ix_monitored_releases_work_id", "monitored_releases", ["work_id"])
    op.create_index("ix_monitored_releases_next_check_at", "monitored_releases", ["next_check_at"])


def downgrade():
    op.drop_index("ix_monitored_releases_next_check_at", table_name="monitored_releases")
    op.drop_index("ix_monitored_releases_work_id", table_name="monitored_releases")
    op.drop_index("ix_monitored_releases_owner_id", table_name="monitored_releases")
    op.drop_table("monitored_releases")
