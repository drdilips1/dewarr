from datetime import UTC, datetime, timedelta
from uuid import UUID

from procrastinate import RetryStrategy
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AuditEvent, Integration, Operation, User
from app.db.session import session_factory
from app.jobs.queue import tasks
from app.jobs.retry import CatalogRetryStrategy


@tasks.task(
    name="organization.publish", queue="imports", retry=RetryStrategy(max_attempts=4, wait=30)
)
async def publish_book(operation_id: str) -> None:
    from app.importing.execution import execute

    await execute(UUID(operation_id))


@tasks.periodic(cron="* * * * *")
@tasks.task(name="organization.confirm", queue="imports", retry=3)
async def schedule_import_confirmation(timestamp: int) -> None:
    from sqlalchemy import text

    from app.db.models import ImportEntry
    from app.jobs.queue import enqueue

    if get_settings().recovery_mode:
        return
    async with session_factory()() as db, db.begin():
        entries = (
            await db.scalars(
                select(ImportEntry)
                .where(
                    ImportEntry.state.in_(["awaiting-library", "cancelling"]),
                    ImportEntry.next_check_at <= datetime.now(UTC),
                )
                .order_by(ImportEntry.id)
                .limit(20)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for entry in entries:
            operation = await db.get(Operation, entry.operation_id)
            status = await db.scalar(
                text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
                {"id": operation.job_id},
            )
            if status in {"todo", "doing"}:
                continue
            operation.status = "queued"
            operation.job_id = await enqueue(
                db, "organization.publish", operation_id=str(operation.id)
            )
            entry.next_check_at = datetime.now(UTC) + timedelta(minutes=1)


@tasks.task(name="organization.probe", queue="inspection", retry=3)
async def check_destination(operation_id: str) -> None:
    from app.importing.destinations import probe_route

    await probe_route(UUID(operation_id))


@tasks.task(name="organization.inspect", queue="inspection", retry=3)
async def inspect_completed_download(operation_id: str) -> None:
    from app.importing.workflow import run_inspection

    await run_inspection(UUID(operation_id))


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


@tasks.task(name="acquisition.evaluate", queue="acquisition", retry=3)
async def evaluate_acquisition(operation_id: str) -> None:
    if get_settings().recovery_mode:
        raise RuntimeError("Request evaluation is paused for recovery")
    from app.db.models import AcquisitionIntent
    from app.domain.acquisition import evaluate
    from app.domain.work_graph import acquisition_lock

    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, UUID(operation_id))
        if (
            not operation
            or operation.kind != "acquisition.evaluate"
            or operation.status == "completed"
        ):
            return
        intent = await db.get(AcquisitionIntent, UUID(operation.payload["intent_id"]))
        await acquisition_lock(db, intent.work_id)
        await db.refresh(operation, with_for_update=True)
        if operation.status == "completed":
            return
        user = await db.get(User, intent.owner_id)
        await evaluate(db, user, intent)
        operation.status, operation.message = (
            "completed",
            "Wanted media rechecked against your library",
        )


@tasks.periodic(cron="*/5 * * * *")
@tasks.task(name="acquisition.reconcile", queue="acquisition", retry=3)
async def reconcile_acquisition(timestamp: int) -> None:
    from app.domain.acquisition import reconcile_requests

    await reconcile_requests()


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
