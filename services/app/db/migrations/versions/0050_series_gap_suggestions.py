"""Suggest missing books in series already linked to the library."""

import sqlalchemy as sa
from alembic import op

revision = "0050_series_gap_suggestions"
down_revision = "0049_request_permissions"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "catalog_accounts",
        sa.Column(
            "suggest_series_gaps",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "catalog_accounts",
        sa.Column("series_gap_checked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "series_gap_dismissals",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("provider", sa.String(40), primary_key=True),
        sa.Column("external_id", sa.String(200), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "series_gap_baselines",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("provider", sa.String(40), primary_key=True),
        sa.Column("external_id", sa.String(200), primary_key=True),
        sa.Column("baselined_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "series_gap_sightings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column(
            "work_id", sa.Uuid(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "provider", "external_id", "work_id"),
    )
    op.create_index("ix_series_gap_sightings_user_id", "series_gap_sightings", ["user_id"])
    op.create_index("ix_series_gap_sightings_work_id", "series_gap_sightings", ["work_id"])
    op.create_index(
        "ix_series_gap_sightings_unseen",
        "series_gap_sightings",
        ["user_id"],
        postgresql_where=sa.text("seen_at IS NULL"),
    )


def downgrade():
    bind = op.get_bind()
    occupied = bind.scalar(
        sa.text(
            """
            SELECT
                EXISTS (SELECT 1 FROM series_gap_sightings)
                OR EXISTS (SELECT 1 FROM series_gap_dismissals)
                OR EXISTS (SELECT 1 FROM series_gap_baselines)
                OR EXISTS (SELECT 1 FROM catalog_accounts WHERE suggest_series_gaps)
            """
        )
    )
    if occupied:
        raise RuntimeError(
            "Restore a pre-upgrade backup rather than discarding series gap suggestions"
        )
    op.drop_index("ix_series_gap_sightings_unseen", table_name="series_gap_sightings")
    op.drop_index("ix_series_gap_sightings_work_id", table_name="series_gap_sightings")
    op.drop_index("ix_series_gap_sightings_user_id", table_name="series_gap_sightings")
    op.drop_table("series_gap_sightings")
    op.drop_table("series_gap_baselines")
    op.drop_table("series_gap_dismissals")
    op.drop_column("catalog_accounts", "series_gap_checked_at")
    op.drop_column("catalog_accounts", "suggest_series_gaps")
