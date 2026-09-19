"""Restricted recovery tasks; no dispatch, publication or periodic registrations."""

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


@tasks.task(
    name="recovery.reconcile", queue="recovery", retry=ShelfRetryStrategy(max_attempts=3, wait=60)
)
async def reconcile_restored_transfers(operation_id: str) -> None:
    from app.domain.recovery_reconciliation import run

    await run(UUID(operation_id))


@tasks.task(
    name="recovery.inventory", queue="recovery", retry=ShelfRetryStrategy(max_attempts=3, wait=60)
)
async def reconcile_restored_inventory(operation_id: str) -> None:
    from app.domain.recovery_inventory import run

    await run(UUID(operation_id))


@tasks.task(
    name="recovery.publication", queue="recovery", retry=ShelfRetryStrategy(max_attempts=3, wait=60)
)
async def reconcile_restored_publication(operation_id: str) -> None:
    from app.domain.recovery_publication import run

    await run(UUID(operation_id))


@tasks.task(
    name="recovery.lists", queue="recovery", retry=ShelfRetryStrategy(max_attempts=3, wait=60)
)
async def rebaseline_restored_lists(operation_id: str) -> None:
    from app.domain.recovery_lists import run

    await run(UUID(operation_id))
