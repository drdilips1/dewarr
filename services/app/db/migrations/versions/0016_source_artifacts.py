"""Encrypted source artifacts and validated torrent manifests.

Revision ID: 0016_artifacts
Revises: 0015_sources
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_artifacts"
down_revision = "0015_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_key", sa.String(40), sa.ForeignKey("source_connections.key"), nullable=False
        ),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("descriptor", postgresql.JSONB(), nullable=False),
        sa.Column("release_snapshot", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("owner_id", "source_key", "source_id", "source_generation", "sha256"),
    )
    op.create_index("ix_source_artifacts_owner_id", "source_artifacts", ["owner_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM source_artifacts)")):
        raise RuntimeError("Source artifact history requires a pre-upgrade backup for rollback")
    op.drop_table("source_artifacts")
