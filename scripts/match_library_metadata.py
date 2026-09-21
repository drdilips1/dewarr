"""Audit or persist confident Hardcover links for the selected admin's owned books.

No local work merges, library edits, or edition-ownership changes are performed.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.api.metadata import reader_match, save_hardcover_match
from app.db.models import CatalogAccount, User, Work, WorkMetadataSource
from app.db.session import session_factory
from app.domain.availability import availability_rows
from app.domain.work_graph import canonical_map, family_ids


async def run(args):
    async with session_factory()() as db:
        query = (
            select(User)
            .join(CatalogAccount, CatalogAccount.user_id == User.id)
            .where(User.active.is_(True), User.role == "admin", CatalogAccount.enabled.is_(True))
        )
        if args.user_id:
            query = query.where(User.id == UUID(args.user_id))
        actors = list(await db.scalars(query))
        if len(actors) != 1:
            raise SystemExit("Select one connected administrator with --user-id.")
        actor_id = actors[0].id
        mapping = canonical_map()
        owned = (
            availability_rows(actors[0], mapping).with_only_columns(mapping.c.work_id).distinct()
        )
        works = (
            await db.execute(
                select(Work.id, Work.title)
                .where(Work.id.in_(owned))
                .order_by(Work.title, Work.id)
                .limit(args.limit)
            )
        ).all()
    report = []
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    for work_id, title in works:
        async with session_factory()() as db:
            user = await db.get(User, actor_id)
            linked = await db.scalar(
                select(WorkMetadataSource.id).where(
                    WorkMetadataSource.work_id.in_(family_ids(work_id)),
                    WorkMetadataSource.provider == "hardcover",
                    WorkMetadataSource.accepted.is_(True),
                )
            )
            if linked:
                row = {"work_id": str(work_id), "title": title, "status": "already-linked"}
            else:
                try:
                    result = await (
                        save_hardcover_match(work_id, user, db)
                        if args.apply
                        else reader_match(work_id, user, db)
                    )
                    row = {
                        "work_id": str(work_id),
                        "title": title,
                        "status": result.status,
                        "basis": result.basis,
                        "reason": result.reason,
                        "hardcover_id": result.book.external_id if result.book else None,
                    }
                except HTTPException as error:
                    await db.rollback()
                    row = {
                        "work_id": str(work_id),
                        "title": title,
                        "status": "error",
                        "reason": str(error.detail),
                    }
                    if error.status_code == 429:
                        report.append(row)
                        await asyncio.to_thread(
                            path.write_text, json.dumps(report, indent=2) + "\n"
                        )
                        print(
                            "Provider rate limit reached; progress saved. Rerun after cooldown.",
                            flush=True,
                        )
                        return
            report.append(row)
            await asyncio.to_thread(path.write_text, json.dumps(report, indent=2) + "\n")
            print(f"{len(report)}/{len(works)} {row['status']}: {title}", flush=True)
    print(
        json.dumps(
            {
                status: sum(r["status"] == status for r in report)
                for status in sorted({r["status"] for r in report})
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--user-id")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--report", default=".local/hardcover-match-report.json")
    asyncio.run(run(parser.parse_args()))
