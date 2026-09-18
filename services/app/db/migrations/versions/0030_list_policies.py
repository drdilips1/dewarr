"""Versioned list acquisition authority and durable per-book scheduling."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_list_policies"
down_revision = "0029_request_constraints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "list_acquisition_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "list_id", sa.Uuid(), sa.ForeignKey("book_lists.id", ondelete="SET NULL"), unique=True
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
    )
    for column in ("owner_id", "next_check_at"):
        op.create_index(
            f"ix_list_acquisition_policies_{column}", "list_acquisition_policies", [column]
        )
    op.create_table(
        "list_acquisition_books",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "policy_id", sa.Uuid(), sa.ForeignKey("list_acquisition_policies.id"), nullable=False
        ),
        sa.Column("work_id", sa.Uuid(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("intent_id", sa.Uuid(), sa.ForeignKey("acquisition_intents.id")),
        sa.Column("progress", postgresql.JSONB(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("policy_id", "work_id"),
    )
    op.create_index(
        "ix_list_acquisition_books_next_check_at", "list_acquisition_books", ["next_check_at"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM list_acquisition_policies) OR "
            "EXISTS(SELECT 1 FROM operations WHERE kind='lists.policy-preview')"
        )
    ):
        raise RuntimeError("List policy history requires a pre-upgrade backup")
    op.drop_table("list_acquisition_books")
    op.drop_table("list_acquisition_policies")
