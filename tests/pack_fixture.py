from datetime import UTC, datetime
from uuid import UUID

from app.db.models import CatalogSeries, SeriesMembership, Work


async def catalog(database, owner_id, work_ids, name="Coast"):
    async with database() as db, db.begin():
        row = CatalogSeries(
            owner_id=UUID(str(owner_id)),
            provider="hardcover",
            external_id="pack-series",
            name=name,
            generation=1,
            fetched_at=datetime.now(UTC),
        )
        db.add(row)
        await db.flush()
        for index, work_id in enumerate(work_ids, 1):
            work = await db.get(Work, UUID(str(work_id)))
            work.catalog_owner_id = UUID(str(owner_id))
            db.add(
                SeriesMembership(
                    series_id=row.id,
                    external_id=str(index),
                    work_id=work.id,
                    snapshot={
                        "entry_id": str(index),
                        "book": {
                            "provider": "hardcover",
                            "external_id": str(index),
                            "title": work.title,
                            "authors": work.authors,
                        },
                        "position": str(index),
                        "release_date": "2020-01-01",
                        "compilation": False,
                        "partial": False,
                        "canonical_id": None,
                    },
                )
            )
        return row.id
