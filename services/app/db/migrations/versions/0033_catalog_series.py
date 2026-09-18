"""Private series observations with independently mapped member works."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_catalog_series"
down_revision = "0032_request_release_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_series",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(600), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id")),
        sa.UniqueConstraint("owner_id", "provider", "external_id"),
    )
    op.create_index("ix_catalog_series_owner_id", "catalog_series", ["owner_id"])
    op.create_table(
        "series_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "series_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_series.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("work_id", sa.Uuid(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("series_id", "external_id"),
    )
    op.create_index("ix_series_memberships_series_id", "series_memberships", ["series_id"])
    op.create_index("ix_series_memberships_work_id", "series_memberships", ["work_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM catalog_series)")):
        raise RuntimeError("Series history requires a pre-upgrade backup")
    op.drop_table("series_memberships")
    op.drop_table("catalog_series")
