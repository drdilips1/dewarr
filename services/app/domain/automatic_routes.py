"""Shared, explicitly approved routes for unattended list and series acquisitions."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ImportDestination
from app.domain.acquisition_selection import verified_probe
from app.domain.automatic_dispatch import approve_route
from app.domain.downloaders import connection_or_404, mapped_path
from app.importing.destinations import destination_configuration


class PolicyRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_id: UUID
    destination_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class AutomaticRoutes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    downloader_id: UUID
    downloader_generation: int = Field(ge=1)
    routes: dict[Literal["ebook", "audio"], PolicyRoute]


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
