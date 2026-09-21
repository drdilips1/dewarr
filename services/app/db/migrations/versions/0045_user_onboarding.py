"""Remember first-run onboarding without interrupting existing accounts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0045_user_onboarding"
down_revision = "0044_recovery_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "onboarding",
            JSONB(),
            nullable=False,
            server_default=sa.text('\'{"status":"completed","step": 0,"skipped":[]}\'::jsonb'),
        ),
    )
    op.alter_column(
        "users",
        "onboarding",
        server_default=sa.text('\'{"status":"pending","step": 0,"skipped":[]}\'::jsonb'),
    )


def downgrade():
    op.drop_column("users", "onboarding")
