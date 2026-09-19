"""Persist restored queue and subject boundaries across future resume."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_recovery_queue_fences"
down_revision = "0042_recovery_scans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recovery_queue_fences",
        sa.Column(
            "checkpoint_id",
            sa.Uuid(),
            sa.ForeignKey("restore_checkpoints.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("job_id_through", sa.BigInteger(), nullable=False),
        sa.Column("job_count", sa.BigInteger(), nullable=False),
        sa.Column("subject_counts", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "recovery_queue_subjects",
        sa.Column(
            "checkpoint_id",
            sa.Uuid(),
            sa.ForeignKey("restore_checkpoints.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(30), primary_key=True),
        sa.Column("subject_id", sa.Uuid(), primary_key=True),
    )
    op.create_index(
        "ix_recovery_queue_subject_lookup", "recovery_queue_subjects", ["kind", "subject_id"]
    )
    # Freeze this migration's backfill; do not import the mutable runtime implementation.
    op.execute("""
        INSERT INTO recovery_queue_subjects(checkpoint_id,kind,subject_id)
        SELECT c.id,s.kind,s.subject_id FROM restore_checkpoints c CROSS JOIN (
          SELECT 'operation' AS kind,id AS subject_id FROM operations
          WHERE kind NOT LIKE 'recovery.%'
          UNION ALL SELECT 'download-attempt',id FROM download_attempts
          UNION ALL SELECT 'automatic-import',id FROM automatic_imports
          UNION ALL SELECT 'import-continuation',id FROM automatic_import_continuations
          UNION ALL SELECT 'work',id FROM works
        ) s WHERE c.active
    """)
    op.execute("""
        INSERT INTO recovery_queue_fences(checkpoint_id,job_id_through,job_count,subject_counts)
        SELECT c.id,(SELECT coalesce(max(id),0) FROM book_queue.procrastinate_jobs),
          (SELECT count(*) FROM book_queue.procrastinate_jobs),coalesce((
            SELECT jsonb_object_agg(kind,total) FROM (
              SELECT kind,count(*) AS total FROM recovery_queue_subjects
              WHERE checkpoint_id=c.id GROUP BY kind
            ) counts
          ),'{}'::jsonb) FROM restore_checkpoints c WHERE c.active
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM recovery_queue_fences)")):
        raise RuntimeError("Restored queue boundaries require a pre-upgrade backup")
    op.drop_table("recovery_queue_subjects")
    op.drop_table("recovery_queue_fences")
