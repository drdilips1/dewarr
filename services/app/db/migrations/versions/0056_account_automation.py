"""Store optional MyAnonamouse account automation separately from account secrets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0056_account_automation"
down_revision = "0055_seeding_rename"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "source_connections",
        sa.Column(
            "automation",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "source_connections",
        sa.Column(
            "automation_state",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade():
    op.drop_column("source_connections", "automation_state")
    op.drop_column("source_connections", "automation")
