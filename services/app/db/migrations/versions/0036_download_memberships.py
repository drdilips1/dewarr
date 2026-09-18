"""Explicit book selections served by each physical download."""

import sqlalchemy as sa
from alembic import op

revision = "0036_download_memberships"
down_revision = "0035_source_queries"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "download_memberships",
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["selection_id"], ["acquisition_selections.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["download_attempts.id"]),
        sa.PrimaryKeyConstraint("selection_id"),
    )
    op.create_index("ix_download_memberships_attempt_id", "download_memberships", ["attempt_id"])
    op.execute(
        "INSERT INTO download_memberships (selection_id, attempt_id) "
        "SELECT selection_id, id FROM download_attempts"
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM download_memberships m "
            "JOIN download_attempts a ON a.id=m.attempt_id "
            "WHERE m.selection_id != a.selection_id)"
        )
    ):
        raise RuntimeError("Shared download history requires a pre-upgrade backup")
    op.drop_table("download_memberships")
