"""Lossless source observations with one explicit discriminator registry."""

from typing import Annotated

from pydantic import Field

from app.adapters.audiobookbay import ABBRelease
from app.adapters.mam import MAMRelease
from app.adapters.prowlarr import ProwlarrRelease

SourceRelease = Annotated[MAMRelease | ProwlarrRelease | ABBRelease, Field(discriminator="source")]
RELEASE_TYPES = {"mam": MAMRelease, "prowlarr": ProwlarrRelease, "audiobookbay": ABBRelease}
SOURCE_NAMES = {"mam": "MAM", "prowlarr": "Prowlarr indexers", "audiobookbay": "AudiobookBay"}


def release_value(source_key, snapshot):
    if source_key not in RELEASE_TYPES or snapshot.get("source") != source_key:
        raise ValueError("Stored release does not match its source")
    return RELEASE_TYPES[source_key].model_validate(snapshot)
