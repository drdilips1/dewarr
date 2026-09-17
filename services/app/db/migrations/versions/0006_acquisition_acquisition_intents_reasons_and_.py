"""acquisition intents reasons and reservations

Revision ID: 0006_acquisition
Revises: 0005_corrections
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_acquisition"
down_revision = "0005_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_intents",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("specification", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "work_id", "fingerprint"),
    )
    op.create_index(
        op.f("ix_acquisition_intents_owner_id"), "acquisition_intents", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_acquisition_intents_work_id"), "acquisition_intents", ["work_id"], unique=False
    )
    op.create_table(
        "acquisition_reasons",
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('manual', 'list')"),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["acquisition_intents.id"],
        ),
        sa.ForeignKeyConstraint(["list_id"], ["book_lists.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_id", "kind", "reference"),
    )
    op.create_index(
        op.f("ix_acquisition_reasons_intent_id"), "acquisition_reasons", ["intent_id"], unique=False
    )
    op.create_index(
        op.f("ix_acquisition_reasons_list_id"), "acquisition_reasons", ["list_id"], unique=False
    )
    op.create_table(
        "acquisition_reservations",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('planned', 'released')"),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["libraries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_acquisition_reservations_work_id"),
        "acquisition_reservations",
        ["work_id"],
        unique=False,
    )
    op.create_table(
        "acquisition_targets",
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=10), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("satisfied_asset_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("slot IN ('ebook', 'audio', 'either')"),
        sa.CheckConstraint(
            "state IN ('wanted', 'satisfied', 'awaiting-inventory', 'paused', 'cancelled')"
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["acquisition_intents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["acquisition_reservations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["satisfied_asset_id"],
            ["library_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_id", "slot"),
    )
    op.create_index(
        op.f("ix_acquisition_targets_intent_id"), "acquisition_targets", ["intent_id"], unique=False
    )
    op.create_index(
        op.f("ix_acquisition_targets_reservation_id"),
        "acquisition_targets",
        ["reservation_id"],
        unique=False,
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM acquisition_intents)")):
        raise RuntimeError(
            "Acquisition history cannot be preserved by the older schema. "
            "Restore a pre-upgrade backup."
        )
    op.drop_index(op.f("ix_acquisition_targets_reservation_id"), table_name="acquisition_targets")
    op.drop_index(op.f("ix_acquisition_targets_intent_id"), table_name="acquisition_targets")
    op.drop_table("acquisition_targets")
    op.drop_index(
        op.f("ix_acquisition_reservations_work_id"), table_name="acquisition_reservations"
    )
    op.drop_table("acquisition_reservations")
    op.drop_index(op.f("ix_acquisition_reasons_list_id"), table_name="acquisition_reasons")
    op.drop_index(op.f("ix_acquisition_reasons_intent_id"), table_name="acquisition_reasons")
    op.drop_table("acquisition_reasons")
    op.drop_index(op.f("ix_acquisition_intents_work_id"), table_name="acquisition_intents")
    op.drop_index(op.f("ix_acquisition_intents_owner_id"), table_name="acquisition_intents")
    op.drop_table("acquisition_intents")
