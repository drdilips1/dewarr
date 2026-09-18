"""Preserve effective preferences for requests and their independent reasons."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_request_release_policy"
down_revision = "0031_acquisition_defaults"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("acquisition_intents", "acquisition_reasons"):
        op.add_column(table, sa.Column("release_policy", postgresql.JSONB(), nullable=True))


def downgrade():
    connection = op.get_bind()
    for table in ("acquisition_intents", "acquisition_reasons"):
        if connection.scalar(
            sa.text(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE release_policy IS NOT NULL)")
        ):
            raise RuntimeError(
                "Acquisition history cannot be preserved: "
                "request preferences require a pre-upgrade backup"
            )
    for table in ("acquisition_reasons", "acquisition_intents"):
        op.drop_column(table, "release_policy")
