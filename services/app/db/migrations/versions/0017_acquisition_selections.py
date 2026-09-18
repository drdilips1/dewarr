"""Frozen source selections before downloader side effects."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_selections"
down_revision = "0016_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("acquisition_reservations_state_check", "acquisition_reservations")
    op.create_check_constraint(
        "acquisition_reservations_state_check",
        "acquisition_reservations",
        "state IN ('planned', 'selected', 'released')",
    )
    op.create_table(
        "acquisition_selections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("intent_id", sa.Uuid(), sa.ForeignKey("acquisition_intents.id"), nullable=False),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("acquisition_targets.id"), nullable=False),
        sa.Column(
            "reservation_id",
            sa.Uuid(),
            sa.ForeignKey("acquisition_reservations.id"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id"), nullable=False),
        sa.Column("downloader_id", sa.Uuid(), sa.ForeignKey("integrations.id"), nullable=False),
        sa.Column(
            "destination_id", sa.Uuid(), sa.ForeignKey("import_destinations.id"), nullable=False
        ),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("command", postgresql.JSONB(), nullable=False),
        sa.Column("frozen", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.UniqueConstraint("owner_id", "command_key"),
        sa.CheckConstraint("state IN ('prepared', 'cancelled')"),
    )
    for name in ("owner_id", "intent_id", "artifact_id"):
        op.create_index("ix_acquisition_selections_" + name, "acquisition_selections", [name])
    op.create_index(
        "uq_acquisition_selected_reservation",
        "acquisition_selections",
        ["reservation_id"],
        unique=True,
        postgresql_where=sa.text("state = 'prepared'"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM acquisition_selections)")):
        raise RuntimeError(
            "Acquisition selection history requires a pre-upgrade backup for rollback"
        )
    op.drop_table("acquisition_selections")
    op.drop_constraint("acquisition_reservations_state_check", "acquisition_reservations")
    op.create_check_constraint(
        "acquisition_reservations_state_check",
        "acquisition_reservations",
        "state IN ('planned', 'released')",
    )
