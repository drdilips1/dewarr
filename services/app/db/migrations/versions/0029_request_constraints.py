"""Retain hard acquisition constraints independently for every request."""

import sqlalchemy as sa
from alembic import op

revision = "0029_request_constraints"
down_revision = "0028_capacity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_request_download_constraints",
        "acquisition_intents",
        "NOT (specification ? 'download_constraints') OR "
        "jsonb_typeof(specification -> 'download_constraints') = 'object'",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM acquisition_intents
            WHERE specification ? 'download_constraints')
        OR EXISTS (SELECT 1 FROM acquisition_reservations
            WHERE requirements ? 'download_constraints')
        OR EXISTS (SELECT 1 FROM acquisition_selections
            WHERE frozen -> 'requirements' ? 'download_constraints')
        """)
    ):
        raise RuntimeError("Request constraints require a pre-upgrade backup for rollback")
    op.drop_constraint("ck_request_download_constraints", "acquisition_intents", type_="check")
