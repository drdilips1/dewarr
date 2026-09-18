"""Shared, explicitly approved routes for unattended list and series acquisitions."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models import ImportDestination, Integration, Library
from app.domain.acquisition_selection import verified_probe
from app.domain.automatic_dispatch import approve_route
from app.domain.downloaders import connection_or_404, mapped_path
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


async def inherit(db, user, spec, profile, options):
    """Resolve defaults once for a review; validation never renews saved consent."""
    permitted(user)
    downloader_id = options.downloader_id or profile.preferences.downloader_id
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
    if not options.downloader_id:
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
    return AutomaticRoutes(
        downloader_id=downloader_id, downloader_generation=generation, routes=routes
    ), origins


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
        if destination.medium != medium or not verified_probe(destination, config, mapping):
            raise HTTPException(409, "Verify each download-to-library route before activation")
        expected = getattr(spec, medium + "_library_id")
        if expected and expected != destination.library_id:
            raise HTTPException(422, "Destination conflicts with the requested library")
        libraries[medium + "_library_id"] = str(destination.library_id)
        approvals[medium] = approval
    return libraries, approvals
