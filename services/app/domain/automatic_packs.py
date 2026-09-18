"""Coalesce independently authorized pack selections before physical dispatch."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.adapters.contracts import AdapterError
from app.config import get_settings
from app.db.models import AcquisitionSelection, AcquisitionTarget, Operation, User
from app.db.session import session_factory
from app.domain import download_memberships
from app.domain.operations import transaction_lock
from app.jobs.queue import enqueue
from app.jobs.retry import DependencyRetry

KIND = "acquisition.pack-dispatch"
MAX_MEMBERS = 100
WAIT_LIMIT = timedelta(seconds=60)


async def defer(db, operation, selection):
    operation.payload = {
        **operation.payload,
        "pack_dispatch": {
            "state": "waiting",
            "deadline": (datetime.now(UTC) + WAIT_LIMIT).isoformat(),
            "artifact_id": str(selection.artifact_id),
            "selection_ids": [],
        },
    }
    operation.status, operation.message = (
        "running",
        "Pack selected; coordinating independently authorized books",
    )
    operation.job_id = await enqueue(db, KIND, operation_id=str(operation.id))


def ready(operation):
    return bool(
        operation
        and operation.kind == "acquisition.auto-select"
        and operation.status in {"queued", "running"}
        and operation.payload.get("pack_dispatch", {}).get("state") == "waiting"
        and operation.payload.get("selection_id")
    )


async def run(identifier):
    if get_settings().recovery_mode:
        raise DependencyRetry(60)
    from app.domain import automatic_selection, download_attempts

    async with session_factory()() as db, db.begin():
        seed = await db.get(Operation, identifier)
        if not ready(seed):
            return
        artifact_id = seed.payload["pack_dispatch"]["artifact_id"]
        owner_id = seed.owner_id
        await transaction_lock(db, f"pack-dispatch:{owner_id}:{artifact_id}")
        operations = list(
            await db.scalars(
                select(Operation)
                .where(
                    Operation.owner_id == owner_id,
                    Operation.id != identifier,
                    Operation.kind == "acquisition.auto-select",
                    Operation.status.in_(["queued", "running"]),
                    Operation.payload["pack_dispatch"]["artifact_id"].astext == artifact_id,
                    Operation.payload["pack_dispatch"]["state"].astext == "waiting",
                )
                .order_by(Operation.id)
                .limit(MAX_MEMBERS - 1)
            )
        )
        operations = sorted([seed, *operations], key=lambda op: op.id)
        # Commands precede selection/authority/work locks in every acquisition path.
        for operation in operations:
            await transaction_lock(db, f"operation:{owner_id}:auto-download:{operation.id}")
        for operation in operations:
            await transaction_lock(db, f"auto-select:{operation.id}")
            await db.refresh(operation)
        operations = [operation for operation in operations if ready(operation)]
        if not operations:
            return
        selections = [
            await db.get(AcquisitionSelection, UUID(op.payload["selection_id"]))
            for op in operations
        ]
        pairs = list(zip(operations, selections, strict=True))
        for operation, selection in pairs:
            if selection is None:
                automatic_selection.finish(operation, "held", "Saved pack selection is missing")
        pairs = [(op, item) for op, item in pairs if item is not None]
        if not pairs:
            return
        operations, selections = map(list, zip(*pairs, strict=True))
        await download_memberships.lock(db, selections)
        # A current automatic selector for another covered book can finish its own
        # assessment. Never manufacture consent from a wanted target or series row.
        covered = {
            member["work"]["id"]
            for item in selections
            for member in item.frozen["automatic_selection"]["coverage"]["members"]
        }
        pending = await db.scalar(
            select(Operation.id)
            .where(
                Operation.owner_id == owner_id,
                Operation.kind == "acquisition.auto-select",
                Operation.status.in_(["queued", "running"]),
                Operation.payload["work"]["id"].astext.in_(covered),
                Operation.payload["command"]["download_when_ready"].as_boolean().is_(True),
                Operation.payload["selection_id"].astext.is_(None),
            )
            .limit(1)
        )
        if pending and datetime.now(UTC) < min(
            datetime.fromisoformat(op.payload["pack_dispatch"]["deadline"]) for op in operations
        ):
            raise DependencyRetry(2)
        valid = []
        for operation, selection in zip(operations, selections, strict=True):
            try:
                if selection.state != "prepared":
                    raise HTTPException(409, "Pack selection changed; review this request")
                await download_attempts.selection_authority(db, selection, wanted=True)
                valid.append((operation, selection))
            except (HTTPException, AdapterError) as error:
                target = await db.get(
                    AcquisitionTarget, selection.target_id, populate_existing=True
                )
                if (
                    target
                    and target.state == "satisfied"
                    and selection.state in {"prepared", "cancelled"}
                ):
                    from app.domain.acquisition_selection import cancel

                    user = await db.get(User, owner_id)
                    if selection.state == "prepared":
                        await cancel(db, user, selection)
                    operation.payload = {
                        **operation.payload,
                        "pack_dispatch": {**operation.payload["pack_dispatch"], "state": "skipped"},
                    }
                    automatic_selection.finish(
                        operation,
                        "completed",
                        "Requested media is already available; pack child skipped",
                    )
                    continue
                operation.payload = {
                    **operation.payload,
                    "pack_dispatch": {**operation.payload["pack_dispatch"], "state": "held"},
                }
                automatic_selection.finish(
                    operation,
                    "held",
                    str(error.detail) if isinstance(error, HTTPException) else str(error),
                )
        # Routes and media remain explicit. An incompatible selection is never
        # appended to the first group's transfer; it receives its own outcome.
        groups = []
        for pair in valid:
            for group in groups:
                try:
                    download_memberships.require_compatible([group[0][1], pair[1]], automatic=True)
                except HTTPException:
                    continue
                group.append(pair)
                break
            else:
                groups.append([pair])
        user = await db.get(User, owner_id)
        for group in groups:
            lead, selection = group[0]
            try:
                async with db.begin_nested():
                    attempt = await download_attempts.start(
                        db,
                        user,
                        selection.id,
                        f"auto-download:{lead.id}",
                        automatic=True,
                        additional_selection_ids=[item.id for _, item in group[1:]],
                    )
                    members = [str(item.id) for _, item in group]
                    for operation, _ in group:
                        operation.payload = {
                            **operation.payload,
                            "download_id": str(attempt.id),
                            "pack_dispatch": {
                                **operation.payload["pack_dispatch"],
                                "state": "queued",
                                "selection_ids": members,
                            },
                        }
                        automatic_selection.finish(
                            operation,
                            "completed",
                            f"Automatic pack download queued for {len(group)} "
                            "independently authorized books",
                        )
            except (HTTPException, AdapterError) as error:
                for operation, _ in group:
                    await db.refresh(operation)
                    operation.payload = {
                        **operation.payload,
                        "pack_dispatch": {**operation.payload["pack_dispatch"], "state": "held"},
                    }
                    automatic_selection.finish(
                        operation,
                        "held",
                        str(error.detail) if isinstance(error, HTTPException) else str(error),
                    )
