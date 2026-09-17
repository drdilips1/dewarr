"""catalog provider cache accounts and metadata sources

Revision ID: 0004_metadata
Revises: 0003_inventory
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_metadata"
down_revision = "0003_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("versions_medium_check", "versions", type_="check")
    op.create_check_constraint(
        "version_medium", "versions", "medium IN ('ebook', 'audio', 'print', 'unknown')"
    )
    op.create_table(
        "metadata_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "provider_budgets",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("next_request_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "provider_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        op.f("ix_provider_cache_expires_at"), "provider_cache", ["expires_at"], unique=False
    )
    op.create_table(
        "catalog_accounts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "work_metadata_sources",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("manual_match", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id", "provider", "external_id"),
    )
    op.create_index(
        op.f("ix_work_metadata_sources_external_id"),
        "work_metadata_sources",
        ["external_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_metadata_sources_work_id"), "work_metadata_sources", ["work_id"], unique=False
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM versions WHERE medium NOT IN ('ebook', 'audio'))")
    ):
        raise RuntimeError(
            "Catalog print/unknown versions cannot be preserved by the old schema. "
            "Restore a pre-upgrade backup."
        )
    op.drop_constraint("version_medium", "versions", type_="check")
    op.create_check_constraint("versions_medium_check", "versions", "medium IN ('ebook', 'audio')")
    op.drop_index(op.f("ix_work_metadata_sources_work_id"), table_name="work_metadata_sources")
    op.drop_index(op.f("ix_work_metadata_sources_external_id"), table_name="work_metadata_sources")
    op.drop_table("work_metadata_sources")
    op.drop_table("catalog_accounts")
    op.drop_index(op.f("ix_provider_cache_expires_at"), table_name="provider_cache")
    op.drop_table("provider_cache")
    op.drop_table("provider_budgets")
    op.drop_table("metadata_settings")
