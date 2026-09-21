"""Save one Goodreads profile and discovered shelves per reader."""

import sqlalchemy as sa
from alembic import op

revision = "0046_goodreads_accounts"
down_revision = "0045_user_onboarding"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "goodreads_accounts",
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("goodreads_accounts")
