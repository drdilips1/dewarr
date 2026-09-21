"""Reversible canonical grouping; origin records and external bindings stay intact."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.models import (
    AcquisitionIntent,
    AssetContains,
    BookList,
    ListEntry,
    User,
    Version,
    Work,
    WorkMetadataSource,
)
from app.domain.corrections import journal, revision
from app.domain.work_graph import canonical_work, family_ids, graph_lock


async def group_state(db, work_ids):
    ids = set()
    for work_id in work_ids:
        ids.update((await db.scalars(family_ids(work_id))).all())
    rows = (await db.scalars(select(Work).where(Work.id.in_(ids)).order_by(Work.id))).all()
    return {
        "works": [
            {"id": str(work.id), "redirect_to": str(work.redirect_to) if work.redirect_to else None}
            for work in rows
        ]
    }


async def preview_merge(db, source_id, target_id, actor_id):
    source, target = await canonical_work(db, source_id), await canonical_work(db, target_id)
    if source.id != source_id or target.id != target_id:
        raise HTTPException(409, "Open the current book records before merging")
    if source.id == target.id:
        raise HTTPException(422, "Choose two different books")
    if source.catalog_public and not target.catalog_public:
        raise HTTPException(422, "Keep the public catalog book as the main record")
    state = await group_state(db, [source.id, target.id])
    counts = {}
    for name, model, column in (
        ("versions", Version, Version.work_id),
        ("catalog_sources", WorkMetadataSource, WorkMetadataSource.work_id),
        ("list_memberships", ListEntry, ListEntry.work_id),
        ("requests", AcquisitionIntent, AcquisitionIntent.work_id),
    ):
        query = select(func.count()).select_from(model).where(column.in_(family_ids(source.id)))
        if model is ListEntry:
            query = query.join(BookList).where(BookList.owner_id == actor_id)
        elif model is AcquisitionIntent:
            query = query.where(AcquisitionIntent.owner_id == actor_id)
        counts[name] = await db.scalar(query)
    counts["library_copies"] = await db.scalar(
        select(func.count(func.distinct(AssetContains.asset_id))).where(
            AssetContains.work_id.in_(family_ids(source.id))
        )
    )
    return {
        "source_id": source.id,
        "target_id": target.id,
        "source_title": source.title,
        "target_title": target.title,
        "source_authors": source.authors,
        "target_authors": target.authors,
        "counts": counts,
        "revision": revision(
            {
                "groups": state,
                "source": [source.title, source.authors, source.catalog_public],
                "target": [target.title, target.authors, target.catalog_public],
            }
        ),
    }


async def reconcile_groups(db, work_ids):
    from app.domain.acquisition import evaluate, release_unused

    intents = (
        await db.scalars(
            select(AcquisitionIntent)
            .where(AcquisitionIntent.work_id.in_(work_ids))
            .order_by(AcquisitionIntent.id)
        )
    ).all()
    # Existing reservations cannot bridge newly separated groups during an undo.
    from sqlalchemy import update

    from app.db.models import AcquisitionReservation, AcquisitionSelection, AcquisitionTarget

    if await db.scalar(
        select(AcquisitionReservation.id)
        .where(
            AcquisitionReservation.work_id.in_(work_ids),
            AcquisitionReservation.state == "committed",
        )
        .limit(1)
    ):
        raise HTTPException(409, "Resolve outstanding downloads before changing book identity")

    await db.execute(
        update(AcquisitionSelection)
        .where(
            AcquisitionSelection.reservation_id.in_(
                select(AcquisitionReservation.id).where(
                    AcquisitionReservation.work_id.in_(work_ids),
                )
            ),
            AcquisitionSelection.state == "prepared",
        )
        .values(
            state="cancelled", message="Book identity changed; review the release selection again"
        )
    )

    await db.execute(
        update(AcquisitionTarget)
        .where(AcquisitionTarget.intent_id.in_([intent.id for intent in intents]))
        .values(reservation_id=None)
    )
    await db.execute(
        update(AcquisitionReservation)
        .where(
            AcquisitionReservation.work_id.in_(work_ids),
            AcquisitionReservation.state.in_(["planned", "selected"]),
        )
        .values(state="released")
    )
    for intent in intents:
        await evaluate(db, await db.get(User, intent.owner_id), intent)
    for work_id in work_ids:
        await release_unused(db, work_id)


async def merge_works(db, actor_id, source_id, target_id, expected_revision):
    await graph_lock(db, exclusive=True)
    actor = await db.get(User, actor_id, populate_existing=True)
    if not actor or not actor.active or actor.role != "admin":
        raise HTTPException(403, "Administrator access is required to merge books")
    # No list rows or external operations are modified; graph → work row order
    # cannot conflict with request commands taking list → shared graph locks.
    await db.scalars(
        select(Work).where(Work.id.in_([source_id, target_id])).order_by(Work.id).with_for_update()
    )
    preview = await preview_merge(db, source_id, target_id, actor_id)
    if preview["revision"] != expected_revision:
        raise HTTPException(409, "These books changed. Refresh the merge preview.")
    before = await group_state(db, [source_id, target_id])
    source = await db.get(Work, source_id)
    source.redirect_to = target_id
    await db.flush()
    after = await group_state(db, [source_id, target_id])
    change = await journal(
        db,
        actor_id,
        "work_merge",
        source_id,
        target_id,
        before,
        after,
        f"Merged {preview['source_title']} into {preview['target_title']}",
    )
    await reconcile_groups(db, [UUID(row["id"]) for row in after["works"]])
    return change


async def merge_change_state(db, change, *, lock=False):
    if lock:
        await graph_lock(db, exclusive=True)
    ids = [UUID(row["id"]) for row in change.before["works"]]
    return await group_state(db, ids), ids


async def restore_merge(db, change):
    ids = []
    for row in change.before["works"]:
        work = await db.get(Work, UUID(row["id"]), with_for_update=True)
        work.redirect_to = UUID(row["redirect_to"]) if row["redirect_to"] else None
        if work.id == change.entity_id and not work.redirect_to:
            # Undo must remain visible even when title-based display grouping
            # would otherwise immediately reunite the same two records.
            work.metadata_fields = {**work.metadata_fields, "display_separate": True}
        ids.append(work.id)
    await db.flush()
    await reconcile_groups(db, ids)
