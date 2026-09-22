"""Allow optional sign-in with a Plex account."""

import sqlalchemy as sa
from alembic import op

revision = "0052_plex"
down_revision = "0051_oidc"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "plex_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plex_user_id", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("plex_user_id"),
    )
    op.create_table(
        "plex_login",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("machine_id", sa.String(length=80), nullable=False),
        sa.Column("server_name", sa.String(length=120), nullable=False),
        sa.Column("auto_register", sa.Boolean(), nullable=False),
        sa.Column("default_role", sa.String(length=20), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("default_role IN ('member', 'viewer')"),
        sa.CheckConstraint("client_id <> ''"),
        sa.CheckConstraint("NOT enabled OR machine_id <> ''"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM plex_login) OR EXISTS (SELECT 1 FROM plex_identities)"
        )
    ):
        raise RuntimeError("Restore a pre-upgrade backup rather than dropping Plex account links")
    op.drop_table("plex_login")
    op.drop_table("plex_identities")
