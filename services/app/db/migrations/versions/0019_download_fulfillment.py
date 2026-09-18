"""Historical target fulfillment separate from downloader identity claims."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_fulfillment"
down_revision = "0018_attempts"
branch_labels = None
depends_on = None


def selection_states(expression):
    op.drop_constraint("acquisition_selections_state_check", "acquisition_selections")
    op.create_check_constraint(
        "acquisition_selections_state_check", "acquisition_selections", expression
    )


def upgrade():
    selection_states("state IN ('prepared', 'committed', 'fulfilled', 'cancelled')")
    op.create_table(
        "download_fulfillments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("download_attempts.id"), nullable=False),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("acquisition_targets.id"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("library_assets.id"), nullable=False),
        sa.Column("import_entry_id", sa.Uuid(), sa.ForeignKey("import_entries.id")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("attempt_id", "target_id"),
    )
    for column in ("attempt_id", "target_id"):
        op.create_index("ix_download_fulfillments_" + column, "download_fulfillments", [column])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM download_fulfillments)")):
        raise RuntimeError("Fulfillment history requires a pre-upgrade backup for rollback")
    op.drop_table("download_fulfillments")
    selection_states("state IN ('prepared', 'committed', 'cancelled')")
