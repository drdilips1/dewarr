from datetime import UTC, datetime, timedelta
from uuid import UUID

from procrastinate import RetryStrategy
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AuditEvent, Integration, Operation, User
from app.db.session import session_factory
from app.jobs.queue import tasks
from app.jobs.retry import CatalogRetryStrategy


@tasks.task(name="system.probe", queue="system", retry=3)
async def system_probe(operation_id: str) -> None:
    async with session_factory()() as db, db.begin():
        operation = await db.scalar(
            select(Operation).where(Operation.id == UUID(operation_id)).with_for_update()
        )
        if not operation or operation.status == "completed":
            return
        operation.status = "completed"
        operation.message = "The worker received and completed the persistent job"
        db.add(
            AuditEvent(
                actor_id=operation.owner_id,
                action="system.probe.completed",
                entity_id=operation.id,
            )
        )


@tasks.task(name="library.sync", queue="inventory", retry=RetryStrategy(max_attempts=5, wait=60))
async def library_sync(operation_id: str) -> None:
    from app.domain.inventory import synchronize

    await synchronize(UUID(operation_id))


@tasks.task(
    name="metadata.enrich", queue="metadata", retry=CatalogRetryStrategy(max_attempts=5, wait=60)
)
async def enrich_metadata(operation_id: str) -> None:
    from app.domain.catalog_enrichment import enrich

    await enrich(UUID(operation_id))


@tasks.periodic(cron="*/5 * * * *")
@tasks.task(name="library.schedule", queue="system", retry=3)
async def schedule_inventory(timestamp: int) -> None:
    if get_settings().recovery_mode:
        return
    from app.domain.operations import enqueue_sync

    async with session_factory()() as db, db.begin():
        admin = await db.scalar(
            select(User)
            .where(User.role == "admin", User.active.is_(True))
            .order_by(User.created_at)
            .limit(1)
        )
        if not admin:
            return
        records = (
            await db.scalars(
                select(Integration)
                .where(
                    Integration.kind == "audiobookshelf",
                    Integration.enabled.is_(True),
                    Integration.next_sync_at <= datetime.now(UTC),
                )
                .order_by(Integration.id)
                .limit(20)
            )
        ).all()
        for record in records:
            await enqueue_sync(db, admin.id, record.id, f"inventory:{record.id}:{timestamp}")
            record.next_sync_at = datetime.now(UTC) + timedelta(minutes=30)
