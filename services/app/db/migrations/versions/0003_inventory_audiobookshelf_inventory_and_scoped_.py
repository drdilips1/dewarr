"""Audiobookshelf inventory and scoped library evidence

Revision ID: 0003_inventory
Revises: 0002_domain
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_inventory"
down_revision = "0002_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_runs",
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_inventory_runs_integration_id"), "inventory_runs", ["integration_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_runs_operation_id"), "inventory_runs", ["operation_id"], unique=False
    )
    op.create_table(
        "inventory_observations",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("library_external_id", sa.String(length=200), nullable=False),
        sa.Column("item_external_id", sa.String(length=200), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["inventory_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "library_external_id", "item_external_id"),
    )
    op.add_column(
        "integrations",
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column("integrations", sa.Column("last_error", sa.String(length=500), nullable=True))
    op.add_column(
        "integrations", sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("integrations", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "integrations", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_integrations_next_sync_at"), "integrations", ["next_sync_at"], unique=False
    )
    op.add_column(
        "libraries", sa.Column("accessible", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column("libraries", sa.Column("scope_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("library_assets", sa.Column("title", sa.String(length=600), nullable=True))
    op.add_column(
        "library_assets",
        sa.Column(
            "match_status", sa.String(length=40), server_default="unresolved", nullable=False
        ),
    )
    op.add_column(
        "library_assets", sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "library_assets",
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("library_assets_library_id_external_id_key"), "library_assets", type_="unique"
    )
    op.create_unique_constraint(
        "uq_library_asset_medium", "library_assets", ["library_id", "external_id", "medium"]
    )
    op.add_column("operations", sa.Column("integration_id", sa.Uuid(), nullable=True))
    op.add_column(
        "operations",
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.create_index(
        op.f("ix_operations_integration_id"), "operations", ["integration_id"], unique=False
    )
    op.create_foreign_key(
        "fk_operation_integration", "operations", "integrations", ["integration_id"], ["id"]
    )
    op.add_column(
        "works", sa.Column("catalog_public", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column("works", sa.Column("match_key", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_works_match_key"), "works", ["match_key"], unique=False)


def downgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM library_assets GROUP BY library_id, external_id "
                "HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    private_inventory = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM works WHERE catalog_public = false LIMIT 1"))
        .first()
    )
    if duplicates or private_inventory:
        raise RuntimeError(
            "This downgrade cannot preserve mixed-media or private inventory. "
            "Restore a pre-upgrade backup."
        )
    op.drop_index(op.f("ix_works_match_key"), table_name="works")
    op.drop_column("works", "match_key")
    op.drop_column("works", "catalog_public")
    op.drop_constraint("fk_operation_integration", "operations", type_="foreignkey")
    op.drop_index(op.f("ix_operations_integration_id"), table_name="operations")
    op.drop_column("operations", "payload")
    op.drop_column("operations", "integration_id")
    op.drop_constraint("uq_library_asset_medium", "library_assets", type_="unique")
    op.create_unique_constraint(
        op.f("library_assets_library_id_external_id_key"),
        "library_assets",
        ["library_id", "external_id"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("library_assets", "metadata_snapshot")
    op.drop_column("library_assets", "missing_since")
    op.drop_column("library_assets", "match_status")
    op.drop_column("library_assets", "title")
    op.drop_column("libraries", "scope_fingerprint")
    op.drop_column("libraries", "accessible")
    op.drop_index(op.f("ix_integrations_next_sync_at"), table_name="integrations")
    op.drop_column("integrations", "lease_until")
    op.drop_column("integrations", "lease_token")
    op.drop_column("integrations", "next_sync_at")
    op.drop_column("integrations", "last_error")
    op.drop_column("integrations", "capabilities")
    op.drop_table("inventory_observations")
    op.drop_index(op.f("ix_inventory_runs_operation_id"), table_name="inventory_runs")
    op.drop_index(op.f("ix_inventory_runs_integration_id"), table_name="inventory_runs")
    op.drop_table("inventory_runs")
