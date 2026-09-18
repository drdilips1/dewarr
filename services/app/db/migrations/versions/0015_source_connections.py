"""Native source connections and durable session serialization.

Revision ID: 0015_sources
Revises: 0014_import_cancel
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_sources"
down_revision = "0014_import_cancel"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_connections",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("proxy_url", sa.Text(), nullable=True),
        sa.Column("encrypted_secrets", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM source_connections)")):
        raise RuntimeError(
            "Source credentials and session state require a pre-upgrade backup for rollback"
        )
    op.drop_table("source_connections")
