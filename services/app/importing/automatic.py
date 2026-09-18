"""Durable opt-in continuation through the shared reviewed importer."""

import re
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import (
    AcquisitionSelection,
    AutomaticImport,
    AutomaticImportPolicy,
    DownloadAttempt,
    DownloadInspection,
    ImportDestination,
    Operation,
    User,
    Version,
)
from app.db.session import session_factory
from app.domain import download_reviews
from app.domain.operations import transaction_lock
from app.domain.work_graph import canonical_work
from app.importing.destination_view import view as destination_view
from app.importing.grouping import current_grouping
from app.importing.matching import match_group
from app.importing.naming import fingerprint
from app.importing.planning import FreezeInput, GroupSelection, freeze_plan
from app.importing.settings import current_profile
from app.importing.starting import DestinationChoice, ImportInput, start_import
from app.jobs.queue import enqueue

# This is a negative signal, never a positive proof of a book's identity.
PARTIAL = re.compile(r"\b(sample|excerpt|preview|incomplete|truncated)\b", re.I)


async def check_policy(db, row, *, lock=False):
    policy = await db.get(
        AutomaticImportPolicy,
        row.policy_id,
        with_for_update={"read": True} if lock else None,
        populate_existing=True,
    )
    approver = await db.get(User, policy.approved_by, populate_existing=True)
    if (
        get_settings().recovery_mode
        or not policy.enabled
        or policy.generation != row.policy_generation
        or not approver
        or not approver.active
        or approver.role != "admin"
    ):
        raise HTTPException(409, "Automatic import approval changed; review this import")
    destination = await db.get(ImportDestination, policy.destination_id, populate_existing=True)
    current = await destination_view(db, destination)
    if (
        not current.publication_available
        or current.revision != policy.configuration["destination_revision"]
        or not current.probe
        or current.probe.get("source_key") != policy.configuration["source_key"]
        or current.probe.get("source_path") != policy.configuration["source_path"]
    ):
        raise HTTPException(409, "Automatic import route needs verification and renewed approval")
    return policy, approver, destination, current


async def publication_authority(db, run_id, *, lock=False):
    row = await db.scalar(select(AutomaticImport).where(AutomaticImport.import_run_id == run_id))
    if row:
        await check_policy(db, row, lock=lock)


async def schedule(db, attempt, selection):
    policy = await db.scalar(
        select(AutomaticImportPolicy).where(
            AutomaticImportPolicy.destination_id == selection.destination_id,
            AutomaticImportPolicy.enabled.is_(True),
        )
    )
    if not policy:
        return False
    approval = (selection.frozen.get("automatic_selection") or {}).get("dispatch_approval")
    if approval and (
        approval["policy_id"] != str(policy.id)
        or approval["policy_generation"] != policy.generation
        or approval["approved_by"] != str(policy.approved_by)
    ):
        # A new approval cannot silently replace the one frozen before download.
        # Completed files still reach the ordinary, permission-scoped review path.
        return False
    if await db.scalar(select(AutomaticImport.id).where(AutomaticImport.attempt_id == attempt.id)):
        return True
    operation = Operation(
        owner_id=policy.approved_by,
        kind="organization.automatic",
        idempotency_key=f"automatic-import:{attempt.id}",
        payload={"attempt_id": str(attempt.id)},
    )
    db.add(operation)
    await db.flush()
    row = AutomaticImport(
        attempt_id=attempt.id,
        policy_id=policy.id,
        policy_generation=policy.generation,
        operation_id=operation.id,
    )
    db.add(row)
    await db.flush()
    operation.job_id = await enqueue(db, "organization.automatic", automatic_id=str(row.id))
    attempt.message = "Download complete; checking automatic import eligibility"
    (await db.get(Operation, attempt.operation_id)).message = attempt.message
    return True


async def continue_inspection(db, inspection_id):
    row = await db.scalar(
        select(AutomaticImport).where(
            AutomaticImport.inspection_id == inspection_id, AutomaticImport.state == "inspecting"
        )
    )
    if row:
        operation = await db.get(Operation, row.operation_id)
        operation.job_id = await enqueue(db, "organization.automatic", automatic_id=str(row.id))


async def recover(db, identifier):
    """Repair missing continuations without resetting an exhausted retry budget."""
    await transaction_lock(db, f"automatic-import:{identifier}")
    row = await db.get(AutomaticImport, identifier, populate_existing=True)
    if not row or row.state not in {"queued", "inspecting"}:
        return
    from app.importing.catalog_resolution import pending

    if await pending(db, row):
        return
    operation = await db.get(Operation, row.operation_id, populate_existing=True)

    async def status(job_id):
        return await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": job_id},
        )

    job_status = await status(operation.job_id)
    if job_status in {"todo", "doing"}:
        return
    reason = None
    if job_status in {"failed", "aborted"}:
        reason = "Automatic import retries stopped; open administrator file review"
    elif row.inspection_id:
        inspection = await db.get(DownloadInspection, row.inspection_id)
        if inspection.state not in {"ready", "failed"}:
            inspection_operation = await db.get(Operation, inspection.operation_id)
            if await status(inspection_operation.job_id) not in {"failed", "aborted"}:
                return
            reason = "File inspection retries stopped; retry from administrator file review"
            inspection.state, inspection.message = "failed", reason
            inspection_operation.status, inspection_operation.message = "failed", reason
    if reason:
        row.state, row.message = "held", reason
        operation.status, operation.message = "failed", reason
        return
    operation.job_id = await enqueue(db, "organization.automatic", automatic_id=str(row.id))


def manifest_matches(selection, inspection):
    descriptor = selection.frozen["descriptor"]
    file_scope = inspection.snapshot.get("source_kind") == "file"
    expected = {}
    for item in descriptor["files"]:
        path = PurePosixPath(item["path"])
        relative = str(path if file_scope else path.relative_to(descriptor["name"]))
        expected[relative] = item["size_bytes"]
    actual = {file["path"]: file["identity"]["size"] for file in inspection.snapshot["files"]}
    if actual != expected:
        raise HTTPException(
            409, "Inspected files differ from the completed release; review its contents"
        )


def content_reason(group, files, release):
    """Bounded completeness heuristic, independent of the stricter identity match.

    A complete associated transfer with a valid whole-book container and no partial
    indicators may proceed under the destination's explicit standing approval.
    This is recorded as transfer/container evidence, never a publisher certification.
    """
    if PARTIAL.search(release["title"]):
        return "The release is labelled as partial content"
    selected = [files[file.path] for file in group.files]
    if any(file["state"] != "inspected" for file in selected):
        return "Some media could not be inspected"
    if any(PARTIAL.search(file["path"]) for file in selected):
        return "A file is labelled as partial content"
    if group.medium == "ebook":
        if len(selected) != 1 or selected[0]["extension"] != "epub":
            return "This ebook grouping needs completeness review"
        return None
    if any(file["extension"] not in {"m4b", "mp3"} for file in selected):
        return "This audio format needs completeness review"
    if len(selected) == 1:
        tags = (selected[0].get("technical") or {}).get("tags", {})
        if str(tags.get("track", "1")) not in {"1", "1/1"} or str(tags.get("disc", "1")) not in {
            "1",
            "1/1",
        }:
            return "This audio file may be one part of a larger recording"
        return None
    totals, tracks, discs = set(), [], set()
    for file in selected:
        tags = (file.get("technical") or {}).get("tags", {})
        track = re.fullmatch(r"([1-9]\d{0,3})/([1-9]\d{0,3})", str(tags.get("track", "")))
        if not track:
            return "Multiple audio files need explicit track totals before automatic import"
        tracks.append(int(track[1]))
        totals.add(int(track[2]))
        discs.add(str(tags.get("disc", "1")))
    if (
        not discs <= {"1", "1/1"}
        or totals != {len(selected)}
        or sorted(tracks) != list(range(1, len(selected) + 1))
    ):
        return "Audio tracks are incomplete, duplicated or span unreviewed discs"
    return None


async def plan_ready(db, row, selection, inspection, approver, destination, current):
    await transaction_lock(db, f"inspection-plan:{inspection.id}")
    await download_reviews.validate_inspection(db, inspection.id)
    manifest_matches(selection, inspection)
    grouping_revision, grouping = await current_grouping(db, inspection)
    if len(grouping.groups) > 100:
        raise HTTPException(409, "This collection exceeds the automatic review limit")
    work = await canonical_work(db, UUID(selection.frozen["origin_work_id"]))
    files = {file["path"]: file for file in inspection.snapshot["files"]}
    choices, held, unresolved = [], [], []
    for group in grouping.groups:
        match = await match_group(db, inspection.snapshot, grouping_revision, group)
        reason = content_reason(group, files, selection.frozen["release"])
        if not reason:
            unresolved.append(match)
        candidate = next(
            (item for item in match.candidates if item.version_id == match.selected_version_id),
            None,
        )
        if match.status != "matched" or not candidate:
            reason = match.message
        elif candidate.work_id != work.id:
            reason = "Additional collection titles need an authorized acquisition scope"
        else:
            try:
                await download_reviews.validate_inspection(
                    db, inspection.id, version=await db.get(Version, candidate.version_id)
                )
            except HTTPException:
                reason = "This version does not satisfy the requested media, language or edition"
        if reason:
            held.append({"group_key": group.key, "reason": reason})
            continue
        choices.append(
            GroupSelection(
                group_key=group.key,
                work_id=candidate.work_id,
                version_id=candidate.version_id,
                full_content=True,
                match_revision=match.revision,
            )
        )
    if not choices:
        from app.importing.catalog_resolution import schedule

        if await schedule(db, row, unresolved):
            return
    row.evidence = {
        **row.evidence,
        "schema_version": 1,
        "completeness_basis": "complete-transfer-and-supported-container",
        "held_groups": held,
        "excluded_files": [item.model_dump() for item in grouping.excluded],
    }
    if len(choices) > 1:
        row.state, row.message = (
            "held",
            "Several file groups could satisfy this book; review their versions and grouping",
        )
        return
    if not choices:
        row.state, row.message = (
            "held",
            "No book group qualifies for automatic import; open file review",
        )
        return
    profile = await current_profile(db)
    plan = await freeze_plan(
        db,
        approver,
        inspection.id,
        FreezeInput(
            inspection_revision=inspection.snapshot["revision"],
            profile_revision=fingerprint(profile.model_dump()),
            grouping_revision=grouping_revision,
            selections=choices,
        ),
    )
    imported = await start_import(
        db,
        approver,
        plan.id,
        ImportInput(
            plan_revision=plan.revision,
            destinations={
                destination.medium: DestinationChoice(id=destination.id, revision=current.revision)
            },
        ),
        f"automatic-import:{row.id}",
    )
    row.import_run_id, row.state = imported.id, "importing"
    await enqueue(db, "acquisition.fulfillment", work_id=selection.frozen["origin_work_id"])
    row.message = "Matched books sent to the importer; awaiting library confirmation"
    if held or grouping.excluded:
        row.message += "; other files remain for review"


async def run(identifier):
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, f"automatic-import:{identifier}")
        row = await db.get(AutomaticImport, identifier)
        if not row or row.state in {"held", "importing"}:
            return
        operation = await db.get(Operation, row.operation_id)
        try:
            async with db.begin_nested():
                policy, approver, destination, current = await check_policy(db, row)
                attempt = await db.get(DownloadAttempt, row.attempt_id)
                selection = await db.get(AcquisitionSelection, attempt.selection_id)
                await download_reviews.requester_authority(db, selection)
                if selection.frozen["mapping"]["source_key"] != policy.configuration["source_key"]:
                    raise HTTPException(
                        409, "The completed source is outside this automatic import route"
                    )
                if not row.inspection_id:
                    proposal = await download_reviews.queue_view(db, approver, attempt, selection)
                    claimed = await download_reviews.claim(
                        db, approver, attempt.id, proposal["revision"], f"automatic-review:{row.id}"
                    )
                    row.inspection_id = claimed["inspection_id"]
                    row.state, row.message = (
                        "inspecting",
                        "Inspecting completed files for automatic import",
                    )
                else:
                    inspection = await db.get(DownloadInspection, row.inspection_id)
                    if inspection.state == "failed":
                        raise HTTPException(
                            409, "File inspection failed; open file review to correct it"
                        )
                    if inspection.state == "ready":
                        await plan_ready(
                            db, row, selection, inspection, approver, destination, current
                        )
        except (HTTPException, ValueError) as error:
            await db.refresh(row)
            row.state = "held"
            row.message = (
                str(error.detail)
                if isinstance(error, HTTPException)
                else "File evidence changed; review this automatic import"
            )
        operation.status = (
            "failed"
            if row.state == "held"
            else "completed"
            if row.state == "importing"
            else "running"
        )
        operation.message = row.message
        attempt = await db.get(DownloadAttempt, row.attempt_id)
        attempt.message = row.message
        (await db.get(Operation, attempt.operation_id)).message = row.message
