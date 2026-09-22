"""Join the StoryGraph and release-monitor migrations into one head."""

revision = "0058_join_release_heads"
down_revision = ("0057_storygraph_accounts", "0057_monitored_releases")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
