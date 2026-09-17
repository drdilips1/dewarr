"""reversible identity corrections and edition review

Revision ID: 0005_corrections
Revises: 0004_metadata
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_corrections"
down_revision = "0004_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_changes",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("work_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('asset_match', 'source_detach', 'version_review')"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["undone_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence"),
    )
    op.create_index(
        op.f("ix_identity_changes_entity_id"), "identity_changes", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_identity_changes_work_id"), "identity_changes", ["work_id"], unique=False
    )
    op.add_column("provider_objects", sa.Column("metadata_source_id", sa.Uuid(), nullable=True))
    op.add_column(
        "provider_objects",
        sa.Column("pending_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        op.f("ix_provider_objects_metadata_source_id"),
        "provider_objects",
        ["metadata_source_id"],
        unique=False,
    )
    op.create_foreign_key(
        "provider_objects_metadata_source_id_fkey",
        "provider_objects",
        "work_metadata_sources",
        ["metadata_source_id"],
        ["id"],
    )
    op.execute(
        sa.text("""
        UPDATE provider_objects AS p SET metadata_source_id = s.id
        FROM work_metadata_sources AS s
        WHERE p.kind = 'edition' AND p.work_id = s.work_id
          AND p.provider = s.provider || ':' || s.work_id::text
          AND (SELECT count(*) FROM work_metadata_sources AS sibling
               WHERE sibling.work_id = s.work_id AND sibling.provider = s.provider) = 1
    """)
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM identity_changes)")):
        raise RuntimeError(
            "Correction history cannot be preserved by the older schema. "
            "Restore a pre-upgrade backup."
        )
    op.drop_constraint(
        "provider_objects_metadata_source_id_fkey", "provider_objects", type_="foreignkey"
    )
    op.drop_index(op.f("ix_provider_objects_metadata_source_id"), table_name="provider_objects")
    op.drop_column("provider_objects", "pending_snapshot")
    op.drop_column("provider_objects", "metadata_source_id")
    op.drop_index(op.f("ix_identity_changes_work_id"), table_name="identity_changes")
    op.drop_index(op.f("ix_identity_changes_entity_id"), table_name="identity_changes")
    op.drop_table("identity_changes")
