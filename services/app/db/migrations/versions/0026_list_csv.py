"""Reviewed CSV list snapshots and owner-scoped catalog bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_list_csv"
down_revision = "0025_list_subscriptions"
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
        "list_csv_imports",
        *identity(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "list_id", sa.Uuid(), sa.ForeignKey("book_lists.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("selected_rows", postgresql.JSONB()),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("receipt", postgresql.JSONB()),
    )
    op.create_index("ix_list_csv_imports_owner_id", "list_csv_imports", ["owner_id"])
    op.create_index("ix_list_csv_imports_list_id", "list_csv_imports", ["list_id"])
    op.create_table(
        "list_catalog_bindings",
        *identity(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("identity_key", sa.String(90), nullable=False),
        sa.Column("work_id", sa.Uuid(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("assertion", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("owner_id", "identity_key"),
    )
    op.create_index("ix_list_catalog_bindings_owner_id", "list_catalog_bindings", ["owner_id"])
    op.create_index("ix_list_catalog_bindings_work_id", "list_catalog_bindings", ["work_id"])


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM list_csv_imports) OR "
                "EXISTS(SELECT 1 FROM list_catalog_bindings) OR "
                "EXISTS(SELECT 1 FROM operations WHERE kind='lists.csv')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("CSV list history requires a pre-upgrade backup")
    op.drop_table("list_csv_imports")
    op.drop_table("list_catalog_bindings")
