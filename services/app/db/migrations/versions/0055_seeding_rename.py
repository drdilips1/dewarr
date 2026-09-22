"""Optional qBittorrent rename of the seeding copy into the library folder."""

import sqlalchemy as sa
from alembic import op

revision = "0055_seeding_rename"
down_revision = "0054_download_sources"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "import_destinations",
        sa.Column("seeding_rename", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("import_destinations", sa.Column("client_path", sa.String(1024)))


def downgrade():
    occupied = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM import_destinations WHERE seeding_rename)")
    )
    if occupied:
        raise RuntimeError(
            "Restore a pre-upgrade backup rather than discarding seeding rename settings"
        )
    op.drop_column("import_destinations", "client_path")
    op.drop_column("import_destinations", "seeding_rename")
