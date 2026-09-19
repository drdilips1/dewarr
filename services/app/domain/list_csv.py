"""Reviewed snapshot membership. Commit and its receipt share one database transaction."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import (
    AuditEvent,
    BookList,
    ListCatalogBinding,
    ListCsvImport,
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    User,
    Work,
)
from app.db.session import session_factory
from app.domain.list_subscriptions import catalog_match
from app.domain.operations import transaction_lock
from app.domain.release_profiles import normalized
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_map, canonical_work, graph_lock
from app.importing.match_evidence import isbn_forms
from app.jobs.queue import enqueue


def agrees(left, right):
    if normalized(left["title"]) != normalized(right["title"]):
        return False
    if (
        left["authors"]
        and right["authors"]
        and not (
            {normalized(a) for a in left["authors"]} & {normalized(a) for a in right["authors"]}
        )
    ):
        return False

    def isbns(record):
        return set().union(*(isbn_forms(record.get(k) or "") for k in ("isbn", "isbn13")))

    a, b = isbns(left), isbns(right)
    return not a or not b or bool(a & b)


async def resolve(db, owner, record):
    binding = await db.scalar(
        select(ListCatalogBinding).where(
            ListCatalogBinding.owner_id == owner.id,
            ListCatalogBinding.identity_key == record["identity_key"],
        )
    )
    assertions = [(binding.work_id, binding.assertion)] if binding else []
    if record.get("external_id"):
        observations = (
            await db.scalars(
                select(ListObservation)
                .join(ListSubscription)
                .join(BookList)
                .where(
                    BookList.owner_id == owner.id,
                    ListSubscription.provider == "goodreads",
                    ListObservation.external_id == record["external_id"],
                )
            )
        ).all()
        assertions.extend((r.work_id, r.snapshot) for r in observations)
    roots = {}
    for work_id, assertion in assertions:
        work = await canonical_work(db, work_id)
        if not await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(owner))):
            return None, "Previous catalog access changed; resolve this identity before importing"
        if not agrees(record, assertion):
            return (
                None,
                "This book ID has conflicting title, author or ISBN data; "
                "skip it and review the source",
            )
        roots[work.id] = work
    if len(roots) > 1:
        return (
            None,
            "This book ID is linked to different catalog books; resolve those identities first",
        )
    if roots:
        return next(iter(roots.values())), None
    return await catalog_match(db, owner, record, previous=False, create=False), None


async def repair(db, row):
    operation = await db.get(Operation, row.operation_id) if row.operation_id else None
    if operation and operation.status in {"queued", "running"}:
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        if status not in {"todo", "doing"}:
            operation.status, operation.message = (
                "failed",
                "CSV import worker stopped; retry the saved selection",
            )
    return operation


async def start(db, owner, list_id, row, selected):
    if get_settings().recovery_mode:
        raise HTTPException(409, "CSV imports are paused for recovery")
    selected = sorted(set(selected))
    valid = {record["row_number"] for record in row.snapshot["records"]}
    if not selected or not set(selected) <= valid:
        raise HTTPException(422, "Select at least one valid preview row")
    if row.selected_rows is not None and row.selected_rows != selected:
        raise HTTPException(
            409, "This preview already has a saved selection; upload a new preview to change it"
        )
    operation = await repair(db, row)
    if row.committed_at or (operation and operation.status in {"queued", "running"}):
        return operation
    if row.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "This CSV preview expired; upload the file again")
    if any(r.get("issue") for r in row.snapshot["records"] if r["row_number"] in selected):
        raise HTTPException(409, "Skip rows with identity conflicts before importing")
    row.selected_rows = selected
    if not operation:
        operation = Operation(
            owner_id=owner.id,
            kind="lists.csv",
            idempotency_key=f"csv:{row.id}",
            payload={"list_id": str(list_id), "import_id": str(row.id)},
        )
        db.add(operation)
        await db.flush()
        row.operation_id = operation.id
    operation.status, operation.message = "queued", "Waiting to import selected CSV books"
    operation.job_id = await enqueue(db, "lists.csv", operation_id=str(operation.id))
    return operation


async def run(operation_id):
    if get_settings().recovery_mode:
        raise RuntimeError("CSV imports are paused for recovery")
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.kind != "lists.csv":
            return
        item = await db.scalar(
            select(BookList)
            .where(BookList.id == UUID(operation.payload["list_id"]))
            .with_for_update()
        )
        # Refresh after the lock: a repeated worker may have waited for the first commit.
        await db.refresh(operation)
        if operation.status in {"completed", "failed"}:
            return
        row = await db.get(ListCsvImport, UUID(operation.payload["import_id"]))
        owner = await db.scalar(
            select(User)
            .where(User.id == operation.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not item
            or not row
            or row.operation_id != operation.id
            or not owner
            or not owner.active
            or owner.role == "viewer"
            or item.owner_id != owner.id
        ):
            operation.status, operation.message = (
                "failed",
                "CSV list or account access changed before import",
            )
            return
        if row.expires_at <= datetime.now(UTC):
            operation.status, operation.message = (
                "failed",
                "CSV preview expired before import; upload again",
            )
            return
        await graph_lock(db)
        await transaction_lock(db, f"goodreads:catalog:{owner.id}")
        selected = set(row.selected_rows)
        records = [r for r in row.snapshot["records"] if r["row_number"] in selected]
        matches = []
        for record in records:
            work, issue = await resolve(db, owner, record)
            expected = record.get("work_id")
            if expected:
                old = await canonical_work(db, UUID(expected))
                if not work or work.id != old.id:
                    issue = "Catalog matching changed since preview; upload again to review"
            if issue:
                operation.status, operation.message = (
                    "failed",
                    f"CSV row {record['row_number']}: {issue}",
                )
                return
            matches.append((record, work))
        # The list and identity graph stay locked throughout commit. Resolve existing
        # membership roots once instead of rebuilding the whole graph per CSV row.
        mapping = canonical_map()
        entries = (
            await db.execute(
                select(ListEntry, mapping.c.work_id)
                .join(mapping, mapping.c.origin_id == ListEntry.work_id)
                .where(ListEntry.list_id == item.id)
            )
        ).all()
        membership = {}
        position = 0
        for entry, root in entries:
            membership.setdefault(root, []).append(entry)
            position = max(position, entry.position)
        added = reused = created = 0
        for record, work in matches:
            if work is None:
                # Repeated records with different IDs can resolve to an earlier imported binding.
                work, _ = await resolve(db, owner, record)
            if work is None:
                work = Work(
                    title=record["title"],
                    authors=record["authors"],
                    provisional=True,
                    catalog_public=False,
                    catalog_owner_id=owner.id,
                )
                db.add(work)
                await db.flush()
                created += 1
            else:
                reused += 1
            binding = await db.scalar(
                select(ListCatalogBinding).where(
                    ListCatalogBinding.owner_id == owner.id,
                    ListCatalogBinding.identity_key == record["identity_key"],
                )
            )
            if not binding:
                db.add(
                    ListCatalogBinding(
                        owner_id=owner.id,
                        identity_key=record["identity_key"],
                        work_id=work.id,
                        assertion={k: record[k] for k in ("title", "authors", "isbn", "isbn13")},
                    )
                )
            if work.id in membership:
                for entry in membership[work.id]:
                    entry.locally_added = True
            else:
                position += 1
                entry = ListEntry(
                    list_id=item.id, work_id=work.id, position=position, locally_added=True
                )
                db.add(entry)
                membership[work.id] = [entry]
                added += 1
                from app.domain.list_writeback import record_change

                await record_change(db, owner, item.id, work.id, True)
            await db.flush()
        row.committed_at = datetime.now(UTC)
        row.receipt = {
            "selected": len(records),
            "added": added,
            "already_listed": len(records) - added,
            "created": created,
            "matched": reused,
        }
        operation.status = "completed"
        operation.message = f"CSV imported: {added} added, {len(records) - added} already listed"
        db.add(
            AuditEvent(
                actor_id=owner.id, action="list.csv.imported", entity_id=row.id, detail=row.receipt
            )
        )
