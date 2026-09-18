"""Independent series acquisition reasons and durable reviewed request sets."""

import sqlalchemy as sa
from alembic import op

revision = "0034_series_requests"
down_revision = "0033_catalog_series"
branch_labels = None
depends_on = None


def replace_constraint(expression, name):
    checks = sa.inspect(op.get_bind()).get_check_constraints("acquisition_reasons")
    for check in checks:
        if "kind" in check["sqltext"]:
            op.drop_constraint(check["name"], "acquisition_reasons", type_="check")
    op.create_check_constraint(name, "acquisition_reasons", expression)


def upgrade():
    replace_constraint("kind IN ('manual', 'list', 'series')", "acquisition_reason_kind")


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM operations WHERE kind='series.requests') "
            "OR EXISTS(SELECT 1 FROM acquisition_reasons WHERE kind='series')"
        )
    ):
        raise RuntimeError("Series request history requires a pre-upgrade backup")
    replace_constraint("kind IN ('manual', 'list')", "acquisition_reasons_kind_check")
