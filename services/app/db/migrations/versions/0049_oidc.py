"""Allow identity-provider accounts alongside local passwords."""

import sqlalchemy as sa
from alembic import op

revision = "0049_oidc"
down_revision = "0048_import_storage"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.create_index(
        "users_email_key",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_table(
        "oidc_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "oidc_provider",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("issuer", sa.String(length=300), nullable=False),
        sa.Column("authorization_endpoint", sa.Text(), nullable=False),
        sa.Column("token_endpoint", sa.Text(), nullable=False),
        sa.Column("userinfo_endpoint", sa.Text(), nullable=False),
        sa.Column("jwks_uri", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("signing_algorithm", sa.String(length=20), nullable=False),
        sa.Column("match_existing", sa.String(length=20), nullable=False),
        sa.Column("auto_register", sa.Boolean(), nullable=False),
        sa.Column("default_role", sa.String(length=20), nullable=False),
        sa.Column("group_claim", sa.String(length=80), nullable=False),
        sa.Column("admin_group", sa.String(length=120), nullable=False),
        sa.Column("member_group", sa.String(length=120), nullable=False),
        sa.Column("viewer_group", sa.String(length=120), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("match_existing IN ('off', 'email', 'username')"),
        sa.CheckConstraint("default_role IN ('member', 'viewer')"),
        sa.CheckConstraint("signing_algorithm IN ('RS256', 'ES256')"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM oidc_provider) "
            "OR EXISTS (SELECT 1 FROM oidc_identities) "
            "OR EXISTS (SELECT 1 FROM users WHERE password_hash IS NULL OR email IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Restore a pre-upgrade backup rather than dropping identity provider links"
        )
    op.drop_table("oidc_provider")
    op.drop_table("oidc_identities")
    op.drop_index("users_email_key", table_name="users")
    op.drop_column("users", "email")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
