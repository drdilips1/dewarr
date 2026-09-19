"""Seal saved approvals separately from future queue job identities."""

import sqlalchemy as sa
from alembic import op

revision = "0044_recovery_approvals"
down_revision = "0043_recovery_queue_fences"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recovery_queue_fences",
        sa.Column("approval_version", sa.Integer(), server_default="0", nullable=False),
    )
    # Ordinary APIs/workers must be stopped. Never infer an inactive legacy
    # checkpoint's original membership from today's records.
    op.execute("""
        INSERT INTO recovery_queue_subjects(checkpoint_id,kind,subject_id)
        SELECT c.id,s.kind,s.subject_id FROM restore_checkpoints c
        JOIN recovery_queue_fences f ON f.checkpoint_id=c.id CROSS JOIN (
          SELECT 'selection' AS kind,id AS subject_id FROM acquisition_selections
          UNION ALL SELECT 'import-plan',id FROM frozen_import_plans
          UNION ALL SELECT 'csv-preview',id FROM list_csv_imports
        ) s WHERE c.active ON CONFLICT DO NOTHING
    """)
    op.execute("""
        UPDATE recovery_queue_fences f SET approval_version=1,subject_counts=coalesce((
          SELECT jsonb_object_agg(kind,total) FROM (
            SELECT kind,count(*) AS total FROM recovery_queue_subjects
            WHERE checkpoint_id=f.checkpoint_id GROUP BY kind
          ) counts
        ),'{}'::jsonb) FROM restore_checkpoints c
        WHERE c.id=f.checkpoint_id AND c.active
    """)


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM recovery_queue_fences WHERE approval_version>0)")
    ):
        raise RuntimeError("Restored approval boundaries require a pre-upgrade backup")
    op.drop_column("recovery_queue_fences", "approval_version")
