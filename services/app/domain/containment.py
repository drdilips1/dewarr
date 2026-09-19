"""Explicit complete-work coverage of one real backend item, never child files."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.adapters.audiobookshelf import ABSItem
from app.db.models import AssetContains, Integration, Library, Version, Work
from app.domain.corrections import asset_state, asset_target, check_revision, evidence, journal
from app.importing.naming import fingerprint
from app.importing.versioning import version_revision


def content_evidence(item, medium):
    return fingerprint(
        {
            "metadata": evidence(item.model_dump(mode="json")),
            "medium": medium,
            "supplementary": item.ebook_supplementary if medium == "ebook" else False,
            "files": sorted(
                [file.model_dump(mode="json") for file in getattr(item, medium)],
                key=lambda value: value["path"],
            ),
        }
    )


async def review(db, actor_id, asset_id, work_ids, expected_revision, *, physical_version=None):
    asset, link = await asset_target(db, asset_id, lock=True)
    before = await asset_state(db, asset, link)
    check_revision(before, expected_revision)
    if physical_version and (
        asset.version_id != physical_version.id or link.version_id != physical_version.id
    ):
        raise HTTPException(409, "The backend has not confirmed this collection edition")
    library = await db.get(Library, asset.library_id)
    integration = await db.get(Integration, library.integration_id)
    item = ABSItem.model_validate(asset.metadata_snapshot)
    files = getattr(item, asset.medium)
    if (
        not library.accessible
        or not integration.enabled
        or asset.state != "present"
        or item.missing
        or item.invalid
        or not getattr(item, f"full_{asset.medium}")
        or (asset.medium == "ebook" and item.ebook_supplementary)
        or not files
        or any(file.inode is None or file.modified is None for file in files)
    ):
        raise HTTPException(409, "Sync an available complete item with file evidence before review")
    ids = sorted(set(work_ids))
    if len(ids) < 2:
        raise HTTPException(422, "Select at least two distinct complete books")
    works = list(await db.scalars(select(Work).where(Work.id.in_(ids), Work.redirect_to.is_(None))))
    if len(works) != len(ids):
        raise HTTPException(409, "A selected book changed or was merged; review its current record")
    asset.containment = {
        "work_ids": [str(value) for value in ids],
        "evidence": content_evidence(item, asset.medium),
        "valid": True,
        **(
            {
                "physical_version_id": str(physical_version.id),
                "physical_work_id": str(physical_version.work_id),
                "physical_version_revision": version_revision(physical_version),
            }
            if physical_version
            else {}
        ),
    }
    # The collection cannot lend its ISBN/narration to any contained work.
    asset.version_id, asset.full_content, asset.match_status = (
        physical_version.id if physical_version else None,
        True,
        "collection",
    )
    link.work_id, link.version_id, link.manual_lock, link.match_status = (
        physical_version.work_id if physical_version else None,
        physical_version.id if physical_version else None,
        True,
        "collection",
    )
    link.snapshot = item.model_dump(mode="json")
    await db.execute(delete(AssetContains).where(AssetContains.asset_id == asset.id))
    db.add_all([AssetContains(asset_id=asset.id, work_id=value, verified=True) for value in ids])
    if physical_version:
        db.add(AssetContains(asset_id=asset.id, work_id=physical_version.work_id, verified=True))
    await db.flush()
    return await journal(
        db,
        actor_id,
        "asset_match",
        asset.id,
        physical_version.work_id if physical_version else None,
        before,
        await asset_state(db, asset, link),
        f"Verified {len(ids)} complete books in one library collection",
    )


async def reconcile(db, asset, link, item):
    """Called under the inventory integration lock after the observation is applied."""
    proof = asset.containment
    valid = bool(proof["valid"] and proof["evidence"] == content_evidence(item, asset.medium))
    version = (
        await db.get(Version, UUID(proof["physical_version_id"]))
        if proof.get("physical_version_id")
        else None
    )
    if proof.get("physical_version_id"):
        valid = bool(
            valid and version and version_revision(version) == proof["physical_version_revision"]
        )
    if not valid:
        asset.containment = {**proof, "valid": False}
    asset.version_id = version.id if valid and version else None
    asset.full_content = valid
    asset.match_status = "collection" if valid else "needs-review"
    await db.execute(
        update(AssetContains).where(AssetContains.asset_id == asset.id).values(verified=False)
    )
    if valid:
        await db.execute(
            update(AssetContains)
            .where(
                AssetContains.asset_id == asset.id,
                AssetContains.work_id.in_(
                    [
                        UUID(value)
                        for value in proof["work_ids"]
                        + ([proof["physical_work_id"]] if version else [])
                    ]
                ),
            )
            .values(verified=True)
        )
