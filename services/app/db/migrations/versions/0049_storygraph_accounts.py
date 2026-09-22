"""Save one StoryGraph session and its discovered lists per reader."""

import sqlalchemy as sa
from alembic import op

revision = "0049_storygraph_accounts"
down_revision = "0048_import_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storygraph_accounts",
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("storygraph_accounts")
