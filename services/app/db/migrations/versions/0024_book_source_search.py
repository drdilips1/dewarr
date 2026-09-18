"""Book source-search results and reusable acquisition preferences."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_book_sources"
down_revision = "0023_source_results"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "acquisition_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("preferences", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_acquisition_profiles_owner_id", "acquisition_profiles", ["owner_id"])
    op.add_column(
        "source_results", sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"))
    )
    op.create_index("ix_source_results_operation_id", "source_results", ["operation_id"])


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM acquisition_profiles) "
                "OR EXISTS(SELECT 1 FROM operations WHERE kind='sources.search')"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Saved profiles or source-search history require a pre-upgrade backup for rollback"
        )
    op.drop_index("ix_source_results_operation_id", table_name="source_results")
    op.drop_constraint("source_results_operation_id_fkey", "source_results", type_="foreignkey")
    op.drop_column("source_results", "operation_id")
    op.drop_table("acquisition_profiles")
