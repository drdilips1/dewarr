"""Recoverable import cancellation states.

Revision ID: 0014_import_cancel
Revises: 0013_import_covers
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_import_cancel"
down_revision = "0013_import_covers"
branch_labels = None
depends_on = None

BASE = "'queued', 'publishing', 'awaiting-library', 'confirmed', 'held', 'skipped'"


def upgrade():
    op.drop_constraint("import_entries_state_check", "import_entries", type_="check")
    op.create_check_constraint(
        "import_entries_state_check",
        "import_entries",
        f"state IN ({BASE}, 'cancelling', 'cancel-held', 'cancelled')",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM import_entries "
            "WHERE state IN ('cancelling', 'cancel-held', 'cancelled'))"
        )
    ):
        raise RuntimeError("Import cancellation history requires a pre-upgrade backup for rollback")
    op.drop_constraint("import_entries_state_check", "import_entries", type_="check")
    op.create_check_constraint("import_entries_state_check", "import_entries", f"state IN ({BASE})")
