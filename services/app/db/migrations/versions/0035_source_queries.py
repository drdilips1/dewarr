"""Preserve query provenance for deduplicated source results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_source_queries"
down_revision = "0034_series_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "source_results",
        sa.Column("query_keys", postgresql.JSONB(), server_default="[]", nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM source_results WHERE query_keys != '[]'::jsonb) "
            "OR EXISTS(SELECT 1 FROM operations WHERE kind='sources.search' "
            "AND payload ? 'query_plan')"
        )
    ):
        raise RuntimeError("Source query history requires a pre-upgrade backup")
    op.drop_column("source_results", "query_keys")
