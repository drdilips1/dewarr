"""Reversible canonical work grouping.

Revision ID: 0007_work_merges
Revises: 0006_acquisition
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_work_merges"
down_revision = "0006_acquisition"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("identity_changes_kind_check", "identity_changes", type_="check")
    op.create_check_constraint(
        "identity_changes_kind_check",
        "identity_changes",
        "kind IN ('asset_match', 'source_detach', 'version_review', 'work_merge')",
    )
    op.create_index("ix_works_redirect_to", "works", ["redirect_to"])
    op.create_check_constraint(
        "work_redirect_not_self", "works", "redirect_to IS NULL OR redirect_to != id"
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM identity_changes WHERE kind = 'work_merge') "
            "OR EXISTS (SELECT 1 FROM works WHERE redirect_to IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Canonical work relationships cannot be preserved by the older application. "
            "Restore a pre-upgrade backup."
        )
    op.drop_constraint("work_redirect_not_self", "works", type_="check")
    op.drop_index("ix_works_redirect_to", "works")
    op.drop_constraint("identity_changes_kind_check", "identity_changes", type_="check")
    op.create_check_constraint(
        "identity_changes_kind_check",
        "identity_changes",
        "kind IN ('asset_match', 'source_detach', 'version_review')",
    )
