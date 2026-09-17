"""Install the reviewed Procrastinate 3.9.0 schema in its own namespace."""

from pathlib import Path

from alembic import op

revision = "0001_queue"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE SCHEMA book_queue")
    op.execute("SET LOCAL search_path = book_queue, public")
    sql = (Path(__file__).parent.parent / "queue-3.9.0.sql").read_text()
    # SQLAlchemy supplies an empty parameter mapping; escape psycopg placeholders.
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))
    op.execute("SET LOCAL search_path = public")


def downgrade() -> None:
    op.execute("DROP SCHEMA book_queue CASCADE")
