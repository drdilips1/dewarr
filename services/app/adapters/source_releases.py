"""Lossless source observations with one explicit discriminator registry."""

from typing import Annotated

from pydantic import Field

from app.adapters.audiobookbay import ABBRelease
from app.adapters.mam import MAMRelease
from app.adapters.prowlarr import ProwlarrRelease
from app.adapters.slskd import SlskdRelease

SourceRelease = Annotated[
    MAMRelease | ProwlarrRelease | ABBRelease | SlskdRelease, Field(discriminator="source")
]
RELEASE_TYPES = {
    "mam": MAMRelease,
    "prowlarr": ProwlarrRelease,
    "audiobookbay": ABBRelease,
    "slskd": SlskdRelease,
}
SOURCE_NAMES = {
    "mam": "MAM",
    "prowlarr": "Prowlarr indexers",
    "audiobookbay": "AudiobookBay",
    "slskd": "Soulseek",
}


def release_value(source_key, snapshot):
    if source_key not in RELEASE_TYPES or snapshot.get("source") != source_key:
        raise ValueError("Stored release does not match its source")
    return RELEASE_TYPES[source_key].model_validate(snapshot)
