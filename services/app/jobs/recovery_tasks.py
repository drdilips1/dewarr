"""The recovery worker has only this read-only task and no periodic registrations."""

from uuid import UUID

import procrastinate

from app.jobs.retry import ShelfRetryStrategy

tasks = procrastinate.Blueprint()


@tasks.task(
    name="recovery.scan", queue="recovery", retry=ShelfRetryStrategy(max_attempts=3, wait=60)
)
async def scan_restored_state(scan_id: str) -> None:
    from app.domain.recovery_scans import run

    await run(UUID(scan_id))
