"""Add Seerr-style permissions and request approval state."""

import sqlalchemy as sa
from alembic import op

revision = "0049_request_permissions"
# Frozen copies of the permission bits in app.domain.permissions.
_ADMIN = 1 << 0
_MANAGE_USERS = 1 << 1
_MANAGE_SETTINGS = 1 << 2
_MANAGE_REQUESTS = 1 << 3
_REQUEST = 1 << 4
_REQUEST_EBOOK = 1 << 5
_REQUEST_AUDIO = 1 << 6
_AUTO_APPROVE = 1 << 7
_AUTO_APPROVE_EBOOK = 1 << 8
_AUTO_APPROVE_AUDIO = 1 << 9
_REQUEST_ADVANCED = 1 << 10
_AUTOMATE = 1 << 11
_ALL = (
    _ADMIN
    | _MANAGE_USERS
    | _MANAGE_SETTINGS
    | _MANAGE_REQUESTS
    | _REQUEST
    | _REQUEST_EBOOK
    | _REQUEST_AUDIO
    | _AUTO_APPROVE
    | _AUTO_APPROVE_EBOOK
    | _AUTO_APPROVE_AUDIO
    | _REQUEST_ADVANCED
    | _AUTOMATE
)
_MEMBER = (
    _REQUEST
    | _REQUEST_EBOOK
    | _REQUEST_AUDIO
    | _AUTO_APPROVE
    | _AUTO_APPROVE_EBOOK
    | _AUTO_APPROVE_AUDIO
    | _REQUEST_ADVANCED
)
down_revision = "0048_import_storage"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "permission_roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("permissions", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.add_column("users", sa.Column("permissions", sa.BigInteger()))
    op.add_column("users", sa.Column("permission_role_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_users_permission_role_id",
        "users",
        "permission_roles",
        ["permission_role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    member_auto = _MEMBER | _AUTOMATE
    op.execute(
        sa.text(
            f"""
            UPDATE users SET permissions = CASE
                WHEN role = 'admin' THEN {_ALL}
                WHEN role = 'viewer' THEN 0
                WHEN can_automate THEN {member_auto}
                ELSE {_MEMBER}
            END
            """
        )
    )
    op.add_column(
        "acquisition_reasons",
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"),
    )
    op.add_column("acquisition_reasons", sa.Column("decided_by", sa.Uuid()))
    op.add_column("acquisition_reasons", sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.add_column("acquisition_reasons", sa.Column("decision_note", sa.String(300)))
    op.create_foreign_key(
        "fk_acquisition_reasons_decided_by",
        "acquisition_reasons",
        "users",
        ["decided_by"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_acquisition_reason_approval",
        "acquisition_reasons",
        "approval_status IN ('pending', 'approved', 'declined')",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM acquisition_reasons "
            "WHERE approval_status <> 'approved' OR decided_by IS NOT NULL)"
        )
    ):
        raise RuntimeError("Restore a pre-upgrade backup rather than discarding request decisions")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM permission_roles)")):
        raise RuntimeError("Restore a pre-upgrade backup rather than discarding saved roles")
    op.drop_constraint("ck_acquisition_reason_approval", "acquisition_reasons")
    op.drop_constraint("fk_acquisition_reasons_decided_by", "acquisition_reasons")
    op.drop_column("acquisition_reasons", "decision_note")
    op.drop_column("acquisition_reasons", "decided_at")
    op.drop_column("acquisition_reasons", "decided_by")
    op.drop_column("acquisition_reasons", "approval_status")
    op.drop_constraint("fk_users_permission_role_id", "users")
    op.drop_column("users", "permission_role_id")
    op.drop_column("users", "permissions")
    op.drop_table("permission_roles")
