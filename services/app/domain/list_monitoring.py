"""Membership episodes and canonical projections without moving historical work origins."""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import case, func, select

from app.db.models import (
    AcquisitionReason,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    ListEntry,
    User,
    Work,
)
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_map, family_ids, graph_lock

PRIORITY = {
    "held": 0,
    "searching": 1,
    "selecting": 2,
    "pending": 3,
    "wanted": 4,
    "available": 5,
    "baseline": 6,
    "removed": 7,
}


def leader(books, active_intents):
    return min(
        books,
        key=lambda book: (
            book.intent_id is not None and book.intent_id not in active_intents,
            book.next_check_at is None and book.state != "available",
            PRIORITY[book.state],
            book.created_at,
            str(book.id),
        ),
    )


def removed(book):
    book.state = "removed"
    book.message = "No longer in this list"
    book.next_check_at = None


async def withdraw_membership(db, list_id, work_id=None):
    """Called under the list lock, even when a removed book has no request yet."""
    conditions = [ListAcquisitionPolicy.list_id == list_id]
    if work_id:
        conditions.append(ListAcquisitionBook.work_id.in_(family_ids(work_id)))
    for book in await db.scalars(
        select(ListAcquisitionBook).join(ListAcquisitionPolicy).where(*conditions)
    ):
        removed(book)


async def identity_groups(db, policy):
    await graph_lock(db)
    books = list(
        await db.scalars(
            select(ListAcquisitionBook).where(ListAcquisitionBook.policy_id == policy.id)
        )
    )
    mapping = canonical_map()
    roots = dict(
        (
            await db.execute(
                select(mapping).where(mapping.c.origin_id.in_([book.work_id for book in books]))
            )
        ).all()
    )
    grouped = defaultdict(list)
    for book in books:
        grouped[str(roots[book.work_id])].append(book)
    return grouped


def reset(book, policy, record, identity, now, *, state, reason, preserve_intent=False):
    previous_intent = book.intent_id
    book.generation = policy.generation
    book.state, book.message = state, reason
    book.next_check_at = now if state == "wanted" else None
    book.progress = {
        "activation": f"{policy.revision}:{uuid4()}",
        "entry_ids": record["entry_ids"],
        "identity": identity,
        "resume_attempts": not preserve_intent and state == "wanted",
    }
    book.intent_id = previous_intent if preserve_intent else None


async def reconcile(db, policy, records, now, *, activation=False, selected=None):
    """Return one scheduling leader per current canonical work.

    Origin rows remain distinct so merge undo can resume their own histories. A
    new membership is distinct from an upstream refresh or a changed graph root.
    """
    selected = selected or set()
    grouped = await identity_groups(db, policy)
    present = {record["work_id"]: record for record in records}
    mapping = canonical_map()
    families = defaultdict(list)
    for origin, root in (
        await db.execute(
            select(mapping).where(mapping.c.work_id.in_([UUID(key) for key in present]))
        )
    ).all():
        families[str(root)].append(str(origin))
    raw_present = set(
        map(
            str,
            await db.scalars(
                select(mapping.c.work_id)
                .join(ListEntry, ListEntry.work_id == mapping.c.origin_id)
                .where(ListEntry.list_id == policy.list_id)
            ),
        )
    )
    new_count = 0
    for root, record in present.items():
        identity = {"root": root, "origins": sorted(families[root])}
        if root not in grouped:
            if not activation and new_count >= 25:
                continue
            book = ListAcquisitionBook(policy_id=policy.id, work_id=UUID(root))
            db.add(book)
            new_count += 1
            grouped[root] = [book]
        for book in grouped[root]:
            progress = book.progress or {}
            old_entries = set(progress.get("entry_ids", []))
            new_episode = book.state == "removed" or (
                bool(old_entries) and not old_entries.intersection(record["entry_ids"])
            )
            identity_changed = (
                progress.get(
                    "identity", {"root": str(book.work_id), "origins": [str(book.work_id)]}
                )
                != identity
            )
            current = book.generation == policy.generation
            if activation:
                if (
                    current
                    and book.state not in {"baseline", "removed"}
                    and not new_episode
                    and root not in selected
                ):
                    if identity_changed:
                        reset(
                            book,
                            policy,
                            record,
                            identity,
                            now,
                            state="wanted",
                            reason="Book identity changed; checking current sources",
                            preserve_intent=True,
                        )
                    else:
                        book.progress = {
                            **progress,
                            "entry_ids": record["entry_ids"],
                            "identity": identity,
                        }
                        book.next_check_at = now
                    continue
                wanted = root in selected
                reset(
                    book,
                    policy,
                    record,
                    identity,
                    now,
                    state="wanted" if wanted else "baseline",
                    reason="Selected for acquisition"
                    if wanted
                    else "Existing member; not selected for acquisition",
                )
            elif not book.id or new_episode or not current:
                future = datetime.fromisoformat(record["added_at"]) > policy.baseline_at
                reset(
                    book,
                    policy,
                    record,
                    identity,
                    now,
                    state="wanted" if future else "baseline",
                    reason="New list addition"
                    if future
                    else "Existing member; preview acquisition first",
                )
            elif identity_changed and book.state not in {"baseline", "removed"}:
                reset(
                    book,
                    policy,
                    record,
                    identity,
                    now,
                    state="wanted",
                    reason="Book identity changed; checking current sources",
                    preserve_intent=True,
                )
            else:
                book.progress = {
                    **deepcopy(progress),
                    "entry_ids": record["entry_ids"],
                    "identity": identity,
                }
    for root, group in grouped.items():
        if root not in present:
            for book in group:
                if root in raw_present:
                    book.state, book.message, book.next_check_at = (
                        "held",
                        "Book access needs attention",
                        None,
                    )
                else:
                    removed(book)
    await db.flush()
    active_intents = set(
        await db.scalars(
            select(AcquisitionReason.intent_id).where(
                AcquisitionReason.reference
                == f"policy:{policy.list_id}:{policy.id}:{policy.generation}",
                AcquisitionReason.active.is_(True),
            )
        )
    )
    return {
        leader([book for book in group if book.generation == policy.generation], active_intents).id
        for root, group in grouped.items()
        if root in present and any(book.generation == policy.generation for book in group)
    }


async def projection(db, policy):
    """A paginatable canonical view; preserve every original row for merge undo."""
    await graph_lock(db)
    owner = await db.get(User, policy.owner_id)
    mapping = canonical_map()
    active = (
        select(AcquisitionReason.id)
        .where(
            AcquisitionReason.intent_id == ListAcquisitionBook.intent_id,
            AcquisitionReason.reference
            == f"policy:{policy.list_id}:{policy.id}:{policy.generation}",
            AcquisitionReason.active.is_(True),
        )
        .exists()
    )
    return (
        select(
            ListAcquisitionBook.id,
            Work.id.label("work_id"),
            Work.title,
            ListAcquisitionBook.state,
            ListAcquisitionBook.message,
            ListAcquisitionBook.intent_id,
            ListAcquisitionBook.next_check_at,
            ListAcquisitionBook.progress,
            ListAcquisitionBook.created_at,
            func.row_number()
            .over(
                partition_by=Work.id,
                order_by=(
                    (ListAcquisitionBook.intent_id.is_not(None) & ~active),
                    (
                        ListAcquisitionBook.next_check_at.is_(None)
                        & (ListAcquisitionBook.state != "available")
                    ),
                    case(PRIORITY, value=ListAcquisitionBook.state, else_=99),
                    ListAcquisitionBook.created_at,
                    ListAcquisitionBook.id,
                ),
            )
            .label("position"),
        )
        .join(mapping, mapping.c.origin_id == ListAcquisitionBook.work_id)
        .join(Work, Work.id == mapping.c.work_id)
        .where(
            ListAcquisitionBook.policy_id == policy.id,
            ListAcquisitionBook.generation == policy.generation,
            visible_work(owner),
        )
        .subquery()
    )
