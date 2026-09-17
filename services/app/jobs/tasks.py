from uuid import UUID

from sqlalchemy import select

from app.db.models import AuditEvent, Operation
from app.db.session import session_factory
from app.jobs.queue import tasks


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
