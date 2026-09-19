"""Explicit Hardcover outbound policies and shared external-list leases."""

import sqlalchemy as sa
from alembic import op

revision = "0039_list_writeback"
down_revision = "0038_asset_containment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "list_writeback_policies",
        sa.Column(
            "list_id",
            sa.Uuid(),
            sa.ForeignKey("book_lists.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("list_subscriptions.id", ondelete="SET NULL"),
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("account_generation", sa.Integer(), nullable=False),
        sa.Column("remote_owner_id", sa.Integer(), nullable=False),
        sa.Column("external_list_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "list_writeback_leases",
        sa.Column("target", sa.String(100), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False),
        sa.Column("token", sa.Uuid(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_operations_list_writeback",
        "operations",
        [sa.text("(payload->>'list_id')"), "created_at"],
        postgresql_where=sa.text("kind = 'lists.writeback'"),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM list_writeback_policies) OR "
            "EXISTS(SELECT 1 FROM operations WHERE kind LIKE 'lists.writeback%')"
        )
    ):
        raise RuntimeError("Hardcover outbound history requires a pre-upgrade backup")
    op.drop_index("ix_operations_list_writeback", table_name="operations")
    op.drop_table("list_writeback_leases")
    op.drop_table("list_writeback_policies")
