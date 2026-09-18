"""Durable downloader side-effect boundary and full torrent identity claims."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_attempts"
down_revision = "0017_selections"
branch_labels = None
depends_on = None


def states(table, expression):
    op.drop_constraint(table + "_state_check", table)
    op.create_check_constraint(table + "_state_check", table, expression)


def selection_index(expression):
    op.drop_index("uq_acquisition_selected_reservation", table_name="acquisition_selections")
    op.create_index(
        "uq_acquisition_selected_reservation",
        "acquisition_selections",
        ["reservation_id"],
        unique=True,
        postgresql_where=sa.text(expression),
    )


def upgrade():
    states("acquisition_reservations", "state IN ('planned', 'selected', 'committed', 'released')")
    states("acquisition_selections", "state IN ('prepared', 'committed', 'cancelled')")
    selection_index("state IN ('prepared', 'committed')")
    op.create_table(
        "download_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "selection_id", sa.Uuid(), sa.ForeignKey("acquisition_selections.id"), nullable=False
        ),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("external_may_exist", sa.Boolean(), nullable=False),
        sa.Column("endpoint_key", sa.String(64), nullable=False),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("receipt", postgresql.JSONB()),
        sa.Column("observation", postgresql.JSONB()),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("download_inspections.id")),
        sa.UniqueConstraint("selection_id"),
        sa.UniqueConstraint("operation_id"),
        sa.CheckConstraint(
            "state IN ('queued', 'preflight', 'submitting', 'uncertain', "
            "'downloading', 'complete', 'held', 'cancelled')"
        ),
        sa.CheckConstraint("NOT external_may_exist OR state != 'cancelled'"),
    )
    for column in ("owner_id", "next_check_at"):
        op.create_index("ix_download_attempts_" + column, "download_attempts", [column])
    op.create_table(
        "download_identity_claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("download_attempts.id"), nullable=False),
        sa.Column("endpoint_key", sa.String(64), nullable=False),
        sa.Column("torrent_hash", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_download_identity_claims_attempt_id", "download_identity_claims", ["attempt_id"]
    )
    op.create_index(
        "uq_active_download_identity",
        "download_identity_claims",
        ["endpoint_key", "torrent_hash"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM download_attempts)")):
        raise RuntimeError("Download attempt history requires a pre-upgrade backup for rollback")
    op.drop_table("download_identity_claims")
    op.drop_table("download_attempts")
    selection_index("state = 'prepared'")
    states("acquisition_selections", "state IN ('prepared', 'cancelled')")
    states("acquisition_reservations", "state IN ('planned', 'selected', 'released')")
