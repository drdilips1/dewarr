"""Reader layouts and tracked public discovery collections."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047_discovery_collections"
down_revision = "0046_goodreads_accounts"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "discovery_layouts",
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("preferences", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "discovery_follows",
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("collection_id", sa.String(200), primary_key=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("tracking", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(600)),
    )


def downgrade():
    op.drop_table("discovery_follows")
    op.drop_table("discovery_layouts")
