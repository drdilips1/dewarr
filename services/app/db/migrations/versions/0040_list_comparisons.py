"""Paged, immutable reviews of local and Hardcover list membership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040_list_comparisons"
down_revision = "0039_list_writeback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "list_comparison_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "comparison_id",
            sa.Uuid(),
            sa.ForeignKey("operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Uuid(), sa.ForeignKey("works.id")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("comparison_id", "position"),
    )
    op.create_index(
        "ix_list_comparison_rows_comparison_id", "list_comparison_rows", ["comparison_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM operations WHERE kind LIKE 'lists.writeback.compare%')"
        )
    ):
        raise RuntimeError("List comparison history requires a pre-upgrade backup")
    op.drop_table("list_comparison_rows")
