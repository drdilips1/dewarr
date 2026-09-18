"""Durable acquisition and import capacity accounting."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_capacity"
down_revision = "0027_hardcover_lists"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "capacity_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("storage_generation", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.create_table(
        "download_capacity",
        sa.Column("attempt_id", sa.UUID(), sa.ForeignKey("download_attempts.id"), primary_key=True),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("slot_active", sa.Boolean(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("resources", postgresql.JSONB(), nullable=False),
        sa.Column("import_resources", postgresql.JSONB(), nullable=False),
        sa.Column("observed_mounts", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_download_capacity_submitted_at", "download_capacity", ["submitted_at"])
    op.create_table(
        "import_capacity",
        sa.Column("entry_id", sa.UUID(), sa.ForeignKey("import_entries.id"), primary_key=True),
        sa.Column("resources", postgresql.JSONB(), nullable=False),
        sa.Column("observed_mounts", postgresql.JSONB(), nullable=False),
    )
    # Existing external attempts are counted conservatively as occupied slots
    # until their normal observer confirms completion. New settings cannot
    # pretend a running transfer disappeared across an upgrade.
    op.execute("""
        INSERT INTO download_capacity
            (attempt_id, automatic, slot_active, submitted_at, resources,
             import_resources, observed_mounts)
        SELECT id, false, external_may_exist AND state != 'complete',
            CASE WHEN external_may_exist THEN created_at ELSE NULL END,
            '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
        FROM download_attempts
    """)
    op.execute("""
        INSERT INTO import_capacity (entry_id, resources, observed_mounts)
        SELECT id, '{}'::jsonb, '{}'::jsonb FROM import_entries
        WHERE reserved AND published_at IS NULL AND state NOT IN ('cancelled', 'skipped')
    """)


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM download_capacity) OR
               EXISTS(SELECT 1 FROM import_capacity) OR
               EXISTS(SELECT 1 FROM capacity_settings)
    """)
        )
        .scalar()
    ):
        raise RuntimeError("Capacity history requires a pre-upgrade backup")
    op.drop_table("import_capacity")
    op.drop_index("ix_download_capacity_submitted_at", table_name="download_capacity")
    op.drop_table("download_capacity")
    op.drop_table("capacity_settings")
