"""Provider-separated list observation and verified membership presence."""

import sqlalchemy as sa
from alembic import op

revision = "0027_hardcover_lists"
down_revision = "0026_list_csv"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "list_subscriptions",
        sa.Column("provider", sa.String(20), nullable=False, server_default="goodreads"),
    )
    op.add_column(
        "list_observations",
        sa.Column("present", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM list_subscriptions WHERE provider!='goodreads') OR "
                "EXISTS(SELECT 1 FROM list_observations WHERE NOT present) OR "
                "EXISTS(SELECT 1 FROM operations WHERE payload->>'provider'='hardcover') OR "
                "EXISTS(SELECT 1 FROM list_catalog_bindings WHERE identity_key LIKE 'hardcover:%')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Hardcover list history requires a pre-upgrade backup")
    op.drop_column("list_observations", "present")
    op.drop_column("list_subscriptions", "provider")
