"""Synthetic grouping benchmark. Requires a test database; all fixtures roll back.

BOOK_TEST_DATABASE_URL=... uv run python scripts/benchmark_catalog_grouping.py
"""

import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

from sqlalchemy import func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    AssetContains,
    Integration,
    Library,
    LibraryAsset,
    LibraryGrant,
    User,
    Work,
)
from app.domain.catalog_display import display_map


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000, 100_000])
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    url = make_url(os.environ["BOOK_TEST_DATABASE_URL"])
    if not url.database or not url.database.endswith("_test"):
        raise SystemExit(
            "Use a dedicated database ending in _test; never the application database."
        )
    engine = create_async_engine(url)
    try:
        for size in args.sizes:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                try:
                    await db.execute(text("SET LOCAL statement_timeout = '30s'"))
                    user = User(
                        username=f"benchmark-{uuid4()}",
                        display_name="Benchmark",
                        password_hash="not-a-login",
                        role="viewer",
                    )
                    integration = Integration(
                        kind="audiobookshelf",
                        name="Benchmark",
                        base_url="http://fixture.invalid",
                        encrypted_secrets="unused",
                    )
                    db.add_all([user, integration])
                    await db.flush()
                    libraries = [
                        Library(
                            integration_id=integration.id, external_id=str(i), name=f"Library {i}"
                        )
                        for i in range(2)
                    ]
                    db.add_all(libraries)
                    await db.flush()
                    db.add_all(
                        [
                            LibraryGrant(user_id=user.id, library_id=library.id)
                            for library in libraries
                        ]
                    )
                    await db.flush()
                    for start in range(0, size, 2000):
                        works, assets, contents = [], [], []
                        for i in range(start, min(start + 2000, size)):
                            work_id, asset_id = uuid4(), uuid4()
                            title = f"Benchmark {i // 2}" + (" (Unabridged)" if i % 2 else "")
                            works.append(
                                {
                                    "id": work_id,
                                    "title": title,
                                    "authors": ["Benchmark Writer"],
                                    "language": "en",
                                    "catalog_public": False,
                                }
                            )
                            assets.append(
                                {
                                    "id": asset_id,
                                    "library_id": libraries[i % 2].id,
                                    "external_id": str(i),
                                    "medium": "audio" if i % 2 else "ebook",
                                    "state": "present",
                                    "full_content": True,
                                    "title": title,
                                }
                            )
                            contents.append(
                                {"asset_id": asset_id, "work_id": work_id, "verified": True}
                            )
                        await db.execute(insert(Work).returning(Work.id), works)
                        await db.execute(insert(LibraryAsset).returning(LibraryAsset.id), assets)
                        await db.execute(
                            insert(AssetContains).returning(AssetContains.asset_id), contents
                        )
                    await db.execute(
                        text(
                            "ANALYZE works, library_assets, asset_contains, "
                            "libraries, library_grants, integrations"
                        )
                    )
                    mapping = display_map(user)
                    query = select(func.count(func.distinct(mapping.c.work_id)))
                    if args.explain:
                        connection = await db.connection()
                        sql = "EXPLAIN (ANALYZE, FORMAT JSON) " + str(
                            query.compile(
                                dialect=engine.dialect, compile_kwargs={"literal_binds": True}
                            )
                        )
                        plan = (await connection.exec_driver_sql(sql)).scalar()
                        from pathlib import Path

                        await asyncio.to_thread(
                            Path(f"/tmp/book-search-grouping-plan-{size}.json").write_text,
                            json.dumps(plan, indent=2),
                        )
                    samples = []
                    for _ in range(3):
                        start = time.perf_counter()
                        groups = await db.scalar(query)
                        samples.append(round(time.perf_counter() - start, 3))
                    print(
                        json.dumps(
                            {
                                "synthetic_records": size,
                                "groups": groups,
                                "reader": "viewer, two private library grants",
                                "seconds": samples,
                            }
                        ),
                        flush=True,
                    )
                finally:
                    await db.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
