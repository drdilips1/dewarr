"""Provider observations kept separate from ordinary sync/acquisition state machines."""

import asyncio
from functools import partial

from app.adapters.audiobookshelf import Audiobookshelf
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import fetch_feed
from app.adapters.grimmory import Grimmory
from app.adapters.qbittorrent import QbitClient, verify_association
from app.domain import hardcover_subscriptions
from app.domain.inventory import summary_fingerprint
from app.domain.recovery_scans import ScanHeld, digest
from app.security import decrypt_secrets


def keyed(rows, field="id"):
    return {row[field]: row for row in rows}


async def downloads(inputs, writer, integration):
    selections = keyed(inputs["acquisition_selections"])
    endpoint = digest({"url": integration["base_url"].rstrip("/")})
    attempts = [
        a
        for a in inputs["download_attempts"]
        if a["endpoint_key"] == endpoint
        or selections[a["selection_id"]]["downloader_id"] == integration["id"]
    ]
    hashes, categories = (
        set(),
        {"book-search", integration["config"].get("category", "book-search")},
    )
    for attempt in attempts:
        frozen = selections[attempt["selection_id"]]["frozen"]
        hashes.update(
            value
            for key, value in frozen["descriptor"].items()
            if key in {"infohash_v1", "infohash_v2"} and value
        )
        categories.add(frozen["downloader"]["category"])
    secret = decrypt_secrets(integration["encrypted_secrets"])
    async with QbitClient(
        integration["base_url"], secret["username"], secret["password"]
    ) as client:
        states, total = await client.census(
            known_hashes=hashes, categories=categories, pulse=writer.pulse
        )
    claimed = set()
    for attempt in attempts:
        frozen = selections[attempt["selection_id"]]["frozen"]
        identities = {
            value
            for key, value in frozen["descriptor"].items()
            if key in {"infohash_v1", "infohash_v2"} and value
        }
        tag = "book-search:" + str(attempt["id"])
        relevant = [state for state in states if tag in state.tags or identities & state.identities]
        evidence = {
            "integration_id": integration["id"],
            "saved_state": attempt["state"],
            "saved_external_may_exist": attempt["external_may_exist"],
            "states": [state.model_dump(mode="json") for state in relevant],
        }
        try:
            if attempt["endpoint_key"] != endpoint:
                raise AdapterError(
                    FailureKind.UNCERTAIN, "The downloader endpoint differs from the saved transfer"
                )
            found = verify_association(
                relevant,
                tag=tag,
                hashes=identities,
                save_path=frozen["downloader"]["save_path"],
                category=frozen["downloader"]["category"],
            )
            if found:
                claimed.add(found.external_id)
                state, message = (
                    "matched",
                    "Current transfer identity and destination match the saved attempt",
                )
            else:
                state, message = (
                    "missing",
                    "Transfer was not observed; absence does not authorize resubmission",
                )
        except AdapterError as error:
            state, message = "conflict", str(error)
        await writer.add(
            "downloads",
            state,
            frozen.get("release", {}).get("raw_title") or "Saved download",
            message,
            entity_id=attempt["id"],
            evidence=evidence,
        )
    for state in states:
        if state.external_id not in claimed:
            await writer.add(
                "downloads",
                "untracked",
                "Unassociated transfer " + state.external_id[:12],
                "Application routing or identity is visible without a restored association",
                evidence={
                    "integration_id": integration["id"],
                    "state": state.model_dump(mode="json"),
                },
            )
    await writer.add(
        "downloads",
        "observed",
        integration["name"],
        "Downloader census completed without changing transfers",
        entity_id=integration["id"],
        evidence={
            "total_transfers": total,
            "relevant_transfers": len(states),
            "unrelated_transfers": total - len(states),
        },
    )


# Audiobookshelf and Grimmory sync both accept this many items in one library.
LIBRARY_ITEM_LIMIT = 100_000


async def abs_library(client, library_id, pulse, *, expand=True, verify=True):
    async def listing(*, expand):
        seen, items, page, expected = {}, [], 0, None
        while True:
            await pulse()
            records, total = await client.page(library_id, page)
            current = summary_fingerprint(records)
            if (
                total > LIBRARY_ITEM_LIMIT
                or (expected is not None and expected != total)
                or len(current) != len(records)
                or seen.keys() & current.keys()
            ):
                raise AdapterError(
                    FailureKind.UNCERTAIN,
                    "Library size or pagination changed, or exceeded 100,000 items",
                )
            if expand and records:
                expanded = await client.expanded(list(current))
                if any(item.library_id != library_id for item in expanded):
                    raise AdapterError(
                        FailureKind.UNCERTAIN, "A library item moved while being read"
                    )
                items.extend(expanded)
            seen.update(current)
            if len(seen) == total:
                return seen, items
            if not records or len(seen) > total:
                raise AdapterError(
                    FailureKind.UNCERTAIN, "Library did not provide complete pagination"
                )
            expected, page = total, page + 1

    first, items = await listing(expand=expand)
    if not verify:
        return first, items
    second, _ = await listing(expand=False)
    if first != second:
        raise AdapterError(FailureKind.UNCERTAIN, "Library changed during verification")
    return first, items


async def read_inventory(client, pulse):
    """Complete, bounded read with unchanged library permissions and membership."""
    await pulse()
    capabilities, scope = await client.authorize()
    libraries = await client.libraries()
    if len(libraries) > 100:
        raise ScanHeld("Recovery supports at most 100 libraries per backend")
    collected, seen, staged = {}, set(), []
    batched = hasattr(client, "refresh_snapshot")
    for library in libraries:
        fingerprint, items = await abs_library(client, library["id"], pulse, verify=not batched)
        staged.append((library["id"], fingerprint))
        ids = {item.id for item in items}
        if seen & ids:
            raise AdapterError(FailureKind.UNCERTAIN, "An item appeared in multiple libraries")
        seen.update(ids)
        collected[library["id"]] = items
    if batched:
        await client.refresh_snapshot()
        for library_id, fingerprint in staged:
            again, _ = await abs_library(client, library_id, pulse, expand=False, verify=False)
            if again != fingerprint:
                raise AdapterError(FailureKind.UNCERTAIN, "Library changed during verification")
    await pulse()
    _, final_scope = await client.authorize()
    if scope != final_scope or sorted(libraries, key=lambda row: row["id"]) != sorted(
        await client.libraries(), key=lambda row: row["id"]
    ):
        raise AdapterError(
            FailureKind.UNCERTAIN, "Backend permissions or libraries changed during review"
        )
    return {
        "scope": scope,
        "libraries": libraries,
        "items": collected,
        "capabilities": capabilities,
    }


def inventory_signature(observation):
    return digest(
        {
            "scope": observation["scope"],
            "libraries": sorted(observation["libraries"], key=lambda row: row["id"]),
            "items": {
                library_id: [
                    item.model_dump(mode="json") for item in sorted(items, key=lambda item: item.id)
                ]
                for library_id, items in observation["items"].items()
            },
        }
    )


def inventory_summary(inputs, integration_id, observation):
    saved = {
        row["external_id"]: row
        for row in inputs["libraries"]
        if row["integration_id"] == integration_id
    }
    assets = [
        row
        for row in inputs["library_assets"]
        if row["library_id"] in {lib["id"] for lib in saved.values()}
    ]
    current = {
        (library_id, item.id, medium)
        for library_id, items in observation["items"].items()
        for item in items
        for medium in ("ebook", "audio")
        if getattr(item, medium)
    }
    library_keys = {lib["id"]: external for external, lib in saved.items()}
    visible = set(observation["items"])
    return {
        "libraries": len(visible),
        "new_libraries": len(visible - saved.keys()),
        "unavailable_libraries": len(saved.keys() - visible),
        "current_items": sum(len(items) for items in observation["items"].values()),
        "ebook_items": sum(key[2] == "ebook" for key in current),
        "audio_items": sum(key[2] == "audio" for key in current),
        "saved_assets": len(assets),
        "missing_media": sum(
            library_keys[asset["library_id"]] in visible
            and (library_keys[asset["library_id"]], asset["external_id"], asset["medium"])
            not in current
            for asset in assets
        ),
    }


async def inventory(inputs, writer, integration):
    saved_libraries = {
        row["external_id"]: row
        for row in inputs["libraries"]
        if row["integration_id"] == integration["id"]
    }
    secrets = decrypt_secrets(integration["encrypted_secrets"])
    client_type = Grimmory if integration["kind"] == "grimmory" else Audiobookshelf
    secret = secrets if integration["kind"] == "grimmory" else secrets["token"]
    async with client_type(integration["base_url"], secret) as client:
        observation = await read_inventory(client, writer.pulse)
    scope, libraries, collected = (
        observation["scope"],
        observation["libraries"],
        observation["items"],
    )
    for external_id, library in saved_libraries.items():
        if external_id not in collected:
            await writer.add(
                "library",
                "inaccessible",
                library["name"],
                "Saved library is no longer visible; missing access cannot prove deleted media",
                entity_id=library["id"],
                evidence={"integration_id": integration["id"]},
            )
    for library in libraries:
        saved = saved_libraries.get(library["id"])
        assets = {
            (a["external_id"], a["medium"]): a
            for a in inputs["library_assets"]
            if saved and a["library_id"] == saved["id"]
        }
        current = {
            (item.id, medium): item
            for item in collected[library["id"]]
            for medium in ("ebook", "audio")
            if getattr(item, medium)
        }
        for key in sorted(assets.keys() | current.keys()):
            asset, item = assets.get(key), current.get(key)
            evidence = {
                "integration_id": integration["id"],
                "external_library_id": library["id"],
                "external_item_id": key[0],
                "medium": key[1],
            }
            if not item:
                state, message = (
                    "missing",
                    "Saved media is absent; check moves before replacement",
                )
                evidence["saved_files"] = asset["files"]
            elif not asset:
                state, message = (
                    "untracked",
                    "Backend media is visible without a restored asset record",
                )
            elif item.missing or item.invalid or not getattr(item, "full_" + key[1]):
                state, message = "changed", "Backend reports missing, invalid or incomplete media"
            elif asset["metadata_snapshot"] != item.model_dump(mode="json"):
                state, message = (
                    "changed",
                    "Current backend metadata or file evidence differs from the backup",
                )
            else:
                state, message = (
                    "matched",
                    "Current backend evidence matches the saved asset observation",
                )
            if item:
                evidence["item"] = item.model_dump(mode="json")
            await writer.add(
                "library",
                state,
                (item.title if item else asset["title"]) or "Saved library item",
                message,
                entity_id=asset["id"] if asset else None,
                evidence=evidence,
            )
        await writer.add(
            "library",
            "observed" if not saved or scope == saved["scope_fingerprint"] else "changed",
            library["name"],
            "Fresh backend inventory collected; owned badges have not been changed",
            entity_id=saved["id"] if saved else None,
            evidence={
                "integration_id": integration["id"],
                "external_library_id": library["id"],
                "scope_fingerprint": scope,
                "items": len(collected[library["id"]]),
            },
        )

    await writer.add(
        "library",
        "inventory-ready",
        integration["name"],
        "Complete backend observation is ready for an explicit inventory refresh review",
        entity_id=integration["id"],
        evidence={
            "inventory_schema": 1,
            "integration_id": integration["id"],
            "inventory_digest": inventory_signature(observation),
            "summary": inventory_summary(inputs, integration["id"], observation),
        },
    )


async def read_shelf(inputs, subscription, pulse):
    item = keyed(inputs["book_lists"])[subscription["list_id"]]
    owner = keyed(inputs["users"]).get(item["owner_id"])
    if not owner or not owner["active"] or owner["role"] == "viewer":
        raise ScanHeld("The list owner no longer has subscription access")
    config = decrypt_secrets(subscription["encrypted_config"])
    if subscription["provider"] == "hardcover":
        account = keyed(inputs["catalog_accounts"], "user_id").get(item["owner_id"])
        if not account or not account["enabled"]:
            raise ScanHeld("The list owner's Hardcover account is unavailable")
        secret = decrypt_secrets(account["encrypted_token"])["token"]
        stage, complete = None, False
        for _ in range(105):
            await pulse()
            for attempt in range(4):
                try:
                    page = await hardcover_subscriptions.fetch_page(
                        item["owner_id"],
                        account["generation"],
                        secret,
                        str(config["external_id"]),
                        stage["cursor"] if stage else 0,
                    )
                    break
                except AdapterError as error:
                    if (
                        error.kind != FailureKind.RATE_LIMIT
                        or (error.retry_after or 1) > 30
                        or attempt == 3
                    ):
                        raise
                    await pulse()
                    await asyncio.sleep(max(error.retry_after or 1, 1))
            stage, complete = hardcover_subscriptions.advance(stage, page)
            if complete:
                break
        if not complete:
            raise ScanHeld(
                "Hardcover did not complete membership verification within its page budget"
            )
        records = hardcover_subscriptions.books(stage)
        complete_snapshot = True
        info = stage["info"]
    elif subscription["provider"] == "goodreads":
        from app.db.session import session_factory
        from app.domain.list_subscriptions import budget

        async with session_factory()() as db, db.begin():
            wait = await budget(db)
        if wait and wait <= 30:
            await pulse()
            await asyncio.sleep(wait)
            async with session_factory()() as db, db.begin():
                wait = await budget(db)
        if wait:
            raise ScanHeld("Goodreads is rate limited; wait before starting another observation")
        await pulse()
        response = await fetch_feed(config["url"])
        if response.not_modified:
            raise ScanHeld("Goodreads did not return fresh feed content")
        records, complete_snapshot = response.items, False
        info = {}
    elif subscription["provider"] == "storygraph":
        from app.adapters.storygraph import open_session, read_list, stored_target
        from app.db.models import StorygraphAccount
        from app.db.session import session_factory
        from app.domain.storygraph_subscriptions import fetch_lock, save_rotation, storygraph_budget

        if not keyed(inputs.get("storygraph_accounts", []), "user_id").get(item["owner_id"]):
            raise ScanHeld("Reconnect StoryGraph before reviewing this list")
        await pulse()
        live = {}
        try:
            async with fetch_lock(item["owner_id"]):
                async with session_factory()() as db, db.begin():
                    row = await db.get(StorygraphAccount, item["owner_id"])
                    if not row:
                        raise ScanHeld("Reconnect StoryGraph before reviewing this list")
                    secret = decrypt_secrets(row.encrypted_config)
                    wait = await storygraph_budget(db, item["owner_id"])
                if wait:
                    raise ScanHeld(
                        "StoryGraph is limiting requests; wait before starting another observation"
                    )
                sent = secret.get("session_cookie")
                try:
                    page = await read_list(
                        open_session(secret),
                        stored_target(config),
                        pause=1.5,
                        session_out=live,
                    )
                finally:
                    rotated = live.get("session_cookie")
                    if rotated and rotated != sent:
                        async with session_factory()() as db, db.begin():
                            await save_rotation(db, item["owner_id"], sent, rotated)
        except AdapterError as error:
            raise ScanHeld(str(error)) from error
        records, complete_snapshot = page.items, False
        info = {"name": page.name}
    else:
        raise ScanHeld("This external list provider has no recovery observer")
    return {"records": records, "complete": complete_snapshot, "info": info}


def shelf_signature(observed):
    return digest(
        {**observed, "records": sorted(observed["records"], key=lambda r: r["external_id"])}
    )


async def shelf(inputs, writer, subscription):
    item = keyed(inputs["book_lists"])[subscription["list_id"]]
    observation = await read_shelf(inputs, subscription, writer.pulse)
    records, complete_snapshot = observation["records"], observation["complete"]
    previous = {
        row["external_id"]: row
        for row in inputs["list_observations"]
        if row["subscription_id"] == subscription["id"]
    }
    policy = next(
        (
            row
            for row in inputs["list_writeback_policies"]
            if row["list_id"] == subscription["list_id"]
        ),
        None,
    )
    config = decrypt_secrets(subscription["encrypted_config"])
    owner_changed = bool(
        policy
        and subscription["provider"] == "hardcover"
        and (
            str(policy["remote_owner_id"]) != observation["info"]["owner_id"]
            or str(policy["external_list_id"]) != str(config["external_id"])
        )
    )
    await writer.add(
        "lists",
        "conflict" if owner_changed else "observed" if complete_snapshot else "partial",
        item["name"],
        "List owner or target differs from the saved write-back policy"
        if owner_changed
        else "Complete current Hardcover memberships verified; no list changes were sent"
        if complete_snapshot
        else "RSS only proves visible additions; missing entries do not prove shelf removal",
        entity_id=subscription["id"],
        evidence={"info": observation["info"], "complete": complete_snapshot},
    )
    current = {record["external_id"]: record for record in records}
    for key in sorted(current.keys() | (previous.keys() if complete_snapshot else set())):
        before, now = previous.get(key), current.get(key)
        if not now:
            state = "missing" if before["present"] else "observed"
        elif not before:
            state = "untracked"
        elif not before["present"] or before["snapshot"] != now:
            state = "changed"
        else:
            state = "matched"
        await writer.add(
            "lists",
            state,
            now["title"] if now else item["name"],
            "Current list membership observed; subscription episodes and automation are unchanged",
            entity_id=subscription["id"],
            evidence={
                "external_id": key,
                "current": now,
                "previous_observation_id": before["id"] if before else None,
                "previous": before["snapshot"] if before else None,
                "complete": complete_snapshot,
            },
        )
    if not owner_changed:
        await writer.add(
            "lists",
            "list-ready",
            item["name"],
            "Current membership is ready for a reviewed baseline; acquisition stays paused",
            entity_id=subscription["id"],
            evidence={
                "list_schema": 1,
                "provider": subscription["provider"],
                "membership_digest": shelf_signature(observation),
                "complete": complete_snapshot,
                "summary": {
                    "visible": len(current),
                    "new": len(current.keys() - previous.keys()),
                    "returned": sum(
                        not previous[key]["present"] for key in current.keys() & previous.keys()
                    ),
                    "missing": sum(
                        previous[key]["present"] for key in previous.keys() - current.keys()
                    )
                    if complete_snapshot
                    else 0,
                    "excluded": sum(row["excluded"] for row in previous.values()),
                },
            },
        )


async def collect(inputs, writer):
    from app.importing.recovery import observe_files

    async def observed(domain, title, identifier, callback):
        try:
            await callback()
        except AdapterError as error:
            await writer.add(
                domain,
                "blocked",
                title,
                str(error),
                entity_id=identifier,
                evidence={"failure": error.kind.value},
            )
        except ScanHeld as error:
            await writer.add(domain, "blocked", title, str(error), entity_id=identifier)
        except (KeyError, ValueError, OSError):
            await writer.add(
                domain,
                "blocked",
                title,
                "Observation is incomplete; check configuration, credentials and mounted paths",
                entity_id=identifier,
            )

    for integration in inputs["integrations"]:
        observer = {
            "qbittorrent": downloads,
            "audiobookshelf": inventory,
            "grimmory": inventory,
        }.get(integration["kind"])
        if not observer:
            continue
        domain = "downloads" if integration["kind"] == "qbittorrent" else "library"
        if not integration["enabled"]:
            await writer.add(
                domain,
                "blocked",
                integration["name"],
                "Connection is disabled; no remote access was attempted",
                entity_id=integration["id"],
            )
            continue
        await observed(
            domain,
            integration["name"],
            integration["id"],
            partial(observer, inputs, writer, integration),
        )
    for subscription in inputs["list_subscriptions"]:
        if not subscription["enabled"]:
            await writer.add(
                "lists",
                "blocked",
                "Disabled list subscription",
                "Current membership has not been observed",
                entity_id=subscription["id"],
            )
            continue
        await observed(
            "lists",
            "External list",
            subscription["id"],
            partial(shelf, inputs, writer, subscription),
        )
    from app.domain import recovery_outbound

    for operation in inputs["outbound"]:
        if operation["status"] in {"completed", "superseded"} and not operation["payload"].get(
            "pending_attempt"
        ):
            continue
        await observed(
            "lists",
            "Saved outbound list change",
            operation["id"],
            partial(recovery_outbound.observe, inputs, writer, operation),
        )
    from app.domain import recovery_access, recovery_commands, recovery_connections

    await recovery_commands.observe(inputs, writer)
    await recovery_access.observe(inputs, writer)
    await recovery_connections.observe(inputs, writer)
    from app.domain import recovery_sources

    await recovery_sources.observe(inputs, writer)
    await observe_files(inputs, writer)
    await writer.add(
        "review",
        "needs-review",
        "Resume remains paused",
        "Observations do not authorize resume. "
        "Downloads, imports, owned badges and list memberships remain unchanged.",
    )
