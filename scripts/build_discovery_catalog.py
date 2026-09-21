"""Refresh reviewed public discovery snapshots. Resume safely; never erase valid data."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.adapters.goodreads_discovery import (
    BASE,
    award_categories,
    category_genres,
    parse_collection,
)

ROOT = Path(__file__).resolve().parents[1] / "services/app/data/discovery"


def save(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--lists-only", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch existing award snapshots")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    collections = {p.stem: json.loads(p.read_text()) for p in ROOT.glob("gr-*.json")}
    report = {"checked_at": datetime.now(UTC).isoformat(), "years": {}, "errors": []}
    if args.lists_only and (ROOT / "coverage.json").exists():
        report = json.loads((ROOT / "coverage.json").read_text())
    async with httpx.AsyncClient(
        timeout=25,
        follow_redirects=False,
        headers={"User-Agent": "BookSearch-DiscoveryCatalog/0.1"},
    ) as client:

        async def get(url):
            await asyncio.sleep(0.6)
            r = await client.get(url)
            r.raise_for_status()
            if len(r.content) > 4 * 1024 * 1024:
                raise ValueError("Response too large")
            return r.content

        for year in [] if args.lists_only else [args.year] if args.year else range(2025, 2008, -1):
            try:
                categories = award_categories(
                    await get(f"{BASE}/choiceawards/best-books-{year}"), year
                )
                if not categories:
                    raise ValueError("No category links available")
                completed = 0
                for url, label in categories.items():
                    try:
                        from app.adapters.goodreads_discovery import source

                        key = source(url)[1]
                        if key in collections and not args.refresh:
                            completed += 1
                            continue
                        v = parse_collection(await get(url), url, label)
                        v["category"] = label
                        v["genres"] = category_genres(label)
                        save(ROOT / f"{v['id']}.json", v)
                        collections[v["id"]] = v
                        completed += 1
                    except Exception as error:
                        report["errors"].append({"url": url, "error": str(error)[:200]})
                report["years"][str(year)] = {"expected": len(categories), "available": completed}
                print(f"{year}: {completed}/{len(categories)} categories", flush=True)
            except Exception as error:
                report["years"][str(year)] = {"expected": None, "available": 0}
                report["errors"].append({"year": year, "error": str(error)[:200]})
                print(f"{year}: unavailable", flush=True)
            save(ROOT / "coverage.json", report)
        for seed in json.loads((ROOT / "seeds.json").read_text()):
            genre, url = seed["genre"], seed["url"]
            try:
                # Numeric Listopia URLs redirect to the current same-list slug.
                from app.adapters.goodreads_discovery import fetch_collection

                v = await fetch_collection(url)
                v["genres"] = [genre]
                save(ROOT / f"{v['id']}.json", v)
                print(f"{genre}: {v['title']} ({len(v['books'])} books)", flush=True)
            except Exception as error:
                report["errors"].append({"genre": genre, "error": str(error)[:200]})
        save(ROOT / "coverage.json", report)


asyncio.run(main())
