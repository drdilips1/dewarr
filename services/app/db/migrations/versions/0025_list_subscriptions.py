"""Private Goodreads shelf observations and source membership provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_list_subscriptions"
down_revision = "0024_book_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("works", sa.Column("catalog_owner_id", sa.Uuid(), sa.ForeignKey("users.id")))
    op.create_index("ix_works_catalog_owner_id", "works", ["catalog_owner_id"])
    op.add_column(
        "list_entries",
        sa.Column("locally_added", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "list_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "list_id",
            sa.Uuid(),
            sa.ForeignKey("book_lists.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("baseline_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_list_subscriptions_next_sync_at", "list_subscriptions", ["next_sync_at"])
    op.create_table(
        "list_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("list_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(80), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("work_id", sa.Uuid(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subscription_id", "external_id"),
    )
    op.create_index(
        "ix_list_observations_subscription_id", "list_observations", ["subscription_id"]
    )
    op.create_index("ix_list_observations_work_id", "list_observations", ["work_id"])


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM list_subscriptions) OR "
                "EXISTS(SELECT 1 FROM works WHERE catalog_owner_id IS NOT NULL) OR "
                "EXISTS(SELECT 1 FROM operations WHERE kind='lists.sync')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Shelf observation/privacy history requires a pre-upgrade backup")
    op.drop_table("list_observations")
    op.drop_table("list_subscriptions")
    op.drop_column("list_entries", "locally_added")
    op.drop_index("ix_works_catalog_owner_id", table_name="works")
    op.drop_constraint("works_catalog_owner_id_fkey", "works", type_="foreignkey")
    op.drop_column("works", "catalog_owner_id")
