"""Request an OpenID Connect group scope only when an administrator sets one."""

import sqlalchemy as sa
from alembic import op

revision = "0051_oidc_group_scope"
down_revision = "0050_plex"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "oidc_provider",
        sa.Column("group_scope", sa.String(length=80), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("oidc_provider", "group_scope")
