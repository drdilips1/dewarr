"""Consolidate verified same-language Hardcover duplicates via reversible identity changes."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.models import CatalogAccount, User
from app.db.session import session_factory
from app.domain.availability import availability_rows
from app.domain.catalog_consolidation import consolidate
from app.domain.work_graph import canonical_map


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
        mapping = canonical_map()
        ids = list(
            await db.scalars(
                availability_rows(actors[0], mapping)
                .with_only_columns(mapping.c.work_id)
                .distinct()
            )
        )
        rows = await consolidate(db, actors[0], ids)
        await db.commit()
        await asyncio.to_thread(Path(args.report).write_text, json.dumps(rows, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "merged": sum(row["status"] == "merged" for row in rows),
                    "needs_review": sum(row["status"] != "merged" for row in rows),
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--user-id")
    parser.add_argument("--report", default=".local/hardcover-consolidation-report.json")
    asyncio.run(run(parser.parse_args()))
