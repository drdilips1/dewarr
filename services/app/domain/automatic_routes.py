"""Shared, explicitly approved routes for unattended list and series acquisitions."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_serializer
from sqlalchemy import select

from app.db.models import ImportDestination, Integration, Library
from app.domain.acquisition_selection import verified_probe
from app.domain.automatic_dispatch import approve_route
from app.domain.downloaders import client_protocol, connection_or_404, mapped_path
from app.domain.visibility import visible_library
from app.importing.destinations import destination_configuration
from app.importing.naming import fingerprint


class PolicyRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_id: UUID
    destination_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class AutomaticRoutes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    downloader_id: UUID | None = None
    downloader_generation: int | None = Field(default=None, ge=1)
    routes: dict[Literal["ebook", "audio"], PolicyRoute] = Field(default_factory=dict)
    alternate_downloader_id: UUID | None = None
    alternate_downloader_generation: int | None = Field(default=None, ge=1)
    alternate_routes: dict[Literal["ebook", "audio"], PolicyRoute] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def compact(self, handler):
        values = handler(self)
        if not values.get("alternate_downloader_id"):
            values.pop("alternate_downloader_id", None)
            values.pop("alternate_downloader_generation", None)
            values.pop("alternate_routes", None)
        return values


def selection_clients(routes, medium):
    """Primary route plus the other protocol when that import route is verified."""
    route = routes.routes[medium]
    values = {
        "downloader_id": routes.downloader_id,
        "downloader_generation": routes.downloader_generation,
        "destination_id": route.destination_id,
        "destination_revision": route.destination_revision,
    }
    alternate = routes.alternate_routes.get(medium)
    if routes.alternate_downloader_id and routes.alternate_downloader_generation and alternate:
        values.update(
            alternate_downloader_id=routes.alternate_downloader_id,
            alternate_downloader_generation=routes.alternate_downloader_generation,
            alternate_destination_id=alternate.destination_id,
            alternate_destination_revision=alternate.destination_revision,
        )
    return values


async def inherit(db, user, spec, profile, options):
    """Resolve defaults once for a review; validation never renews saved consent."""
    permitted(user)
    preferences = profile.preferences
    downloader_id = options.downloader_id
    inherited_legacy = False
    if not downloader_id:
        # A saved torrent client stays primary. The Usenet client is the fallback
        # unless it is the only saved downloader.
        downloader_id = (
            preferences.torrent_downloader_id
            or preferences.downloader_id
            or preferences.usenet_downloader_id
        )
        inherited_legacy = bool(
            preferences.downloader_id
            and not preferences.torrent_downloader_id
            and downloader_id == preferences.downloader_id
        )
    if not downloader_id:
        raise HTTPException(422, "Choose a tested downloader or save a downloader default")
    downloader = await connection_or_404(db, downloader_id)
    generation = options.downloader_generation
    if options.downloader_id:
        if generation is None:
            raise HTTPException(422, "Refresh the selected downloader before previewing")
    else:
        if generation is not None:
            raise HTTPException(422, "Choose a downloader before specifying its revision")
        generation = downloader.credential_generation
    media = {spec.mode} if spec.mode in {"ebook", "audio"} else {"ebook", "audio"}
    if set(options.routes) - media:
        raise HTTPException(422, "Choose destinations only for the requested media")
    routes = {}
    origins = {}
    if not options.downloader_id and inherited_legacy:
        origins["downloader_id"] = profile.origins.get("downloader_id", "Saved default")
    for medium in sorted(media):
        if medium in options.routes:
            route = options.routes[medium]
        else:
            field = medium + "_destination_id"
            destination_id = getattr(profile.preferences, field)
            if not destination_id:
                raise HTTPException(
                    422, "Choose an import destination or save a destination default"
                )
            destination = await db.scalar(
                select(ImportDestination)
                .join(Library)
                .join(Integration)
                .where(
                    ImportDestination.id == destination_id,
                    ImportDestination.enabled.is_(True),
                    Library.accessible.is_(True),
                    Integration.enabled.is_(True),
                    visible_library(user),
                )
            )
            if not destination:
                raise HTTPException(409, "Saved import destination is unavailable; choose a route")
            config = await destination_configuration(db, destination)
            route = PolicyRoute(
                destination_id=destination.id, destination_revision=fingerprint(config)
            )
            origins[field] = profile.origins.get(field, "Saved default")
        routes[medium] = route
    alternate_id, alternate_generation, alternate_routes = await fallback_routes(
        db, user, spec, profile, downloader, routes
    )
    return AutomaticRoutes(
        downloader_id=downloader_id,
        downloader_generation=generation,
        routes=routes,
        alternate_downloader_id=alternate_id,
        alternate_downloader_generation=alternate_generation,
        alternate_routes=alternate_routes,
    ), origins


async def other_client(db, preferences, primary):
    wanted = "nzb" if client_protocol(primary.kind) == "torrent" else "torrent"
    other_id = (
        preferences.usenet_downloader_id if wanted == "nzb" else preferences.torrent_downloader_id
    )
    other = None
    if not other_id and preferences.downloader_id and preferences.downloader_id != primary.id:
        try:
            legacy = await connection_or_404(db, preferences.downloader_id)
        except HTTPException:
            legacy = None
        if legacy and client_protocol(legacy.kind) == wanted:
            other_id, other = legacy.id, legacy
    if not other_id or other_id == primary.id:
        return None
    if other is None:
        try:
            other = await connection_or_404(db, other_id)
        except HTTPException:
            return None
    if not other.enabled or other.status != "connected" or client_protocol(other.kind) != wanted:
        return None
    try:
        mapped_path(other, other.config["save_path"])
    except HTTPException:
        return None
    return other


async def verified_destination(db, user, medium, mapping, preferred_id, library_id):
    rows = list(
        await db.scalars(
            select(ImportDestination)
            .join(Library)
            .join(Integration)
            .where(
                ImportDestination.enabled.is_(True),
                ImportDestination.medium == medium,
                Library.accessible.is_(True),
                Integration.enabled.is_(True),
                visible_library(user),
            )
            .order_by(ImportDestination.name, ImportDestination.id)
        )
    )
    if preferred_id:
        rows.sort(key=lambda row: row.id != preferred_id)
    if library_id:
        rows = [row for row in rows if row.library_id == library_id]
    for destination in rows:
        config = await destination_configuration(db, destination)
        if await verified_probe(db, destination, config, mapping):
            return PolicyRoute(
                destination_id=destination.id, destination_revision=fingerprint(config)
            )
    return None


async def fallback_routes(db, user, spec, profile, primary, routes):
    other = await other_client(db, profile.preferences, primary)
    if not other or not routes:
        return None, None, {}
    other_mapping = mapped_path(other, other.config["save_path"])
    primary_mapping = mapped_path(primary, primary.config["save_path"])
    same_folder = (
        other_mapping["source_key"] == primary_mapping["source_key"]
        and other_mapping["relative_path"] == primary_mapping["relative_path"]
    )
    alternate = {}
    for medium, route in routes.items():
        chosen = route
        if not same_folder:
            chosen = await verified_destination(
                db,
                user,
                medium,
                other_mapping,
                getattr(profile.preferences, medium + "_destination_id", None),
                getattr(spec, medium + "_library_id", None),
            )
        if chosen and await automatic_import_approved(db, user, chosen):
            alternate[medium] = chosen
    if set(alternate) != set(routes):
        return None, None, {}
    return other.id, other.credential_generation, alternate


async def automatic_import_approved(db, user, route):
    """A fallback must not be stored unless unattended grabs can use it."""
    try:
        await approve_route(db, user.id, route.destination_id, route.destination_revision)
    except HTTPException:
        return False
    return True


def permitted(user):
    if (
        not user
        or not user.active
        or user.role == "viewer"
        or (user.role != "admin" and not user.can_automate)
    ):
        raise HTTPException(403, "An administrator must grant automation permission")


async def resolve(db, user, spec, downloader_id, generation, routes):
    permitted(user)
    if not downloader_id or generation is None:
        raise HTTPException(422, "Choose a tested downloader")
    downloader = await connection_or_404(db, downloader_id)
    if (
        not downloader.enabled
        or downloader.status != "connected"
        or downloader.credential_generation != generation
    ):
        raise HTTPException(409, "Downloader settings changed; test and preview again")
    mapping = mapped_path(downloader, downloader.config["save_path"])
    media = {spec.mode} if spec.mode in {"ebook", "audio"} else {"ebook", "audio"}
    if set(routes) != media:
        raise HTTPException(422, "Choose an import destination for each requested medium")
    libraries, approvals = {}, {}
    for medium in sorted(media):
        route = routes[medium]
        approval = await approve_route(
            db, user.id, route.destination_id, route.destination_revision
        )
        destination = await db.get(ImportDestination, route.destination_id)
        config = await destination_configuration(db, destination)
        if destination.medium != medium or not await verified_probe(
            db, destination, config, mapping
        ):
            raise HTTPException(409, "Verify each download-to-library route before activation")
        expected = getattr(spec, medium + "_library_id")
        if expected and expected != destination.library_id:
            raise HTTPException(422, "Destination conflicts with the requested library")
        libraries[medium + "_library_id"] = str(destination.library_id)
        approvals[medium] = approval
    return libraries, approvals
