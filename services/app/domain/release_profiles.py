"""Explainable release preferences, separate from bibliographic identity and ownership."""

import re
import unicodedata
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from sqlalchemy import select

from app.db.models import AcquisitionProfile

FORMATS = {
    "epub",
    "pdf",
    "mobi",
    "azw",
    "azw3",
    "cbz",
    "cbr",
    "m4b",
    "mp3",
    "flac",
    "aac",
    "ogg",
    "opus",
}


class ReleasePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ebook_formats: list[str] = Field(
        default=["epub", "pdf", "azw3", "mobi", "azw", "cbz", "cbr"], min_length=1, max_length=20
    )
    audio_formats: list[str] = Field(
        default=["m4b", "mp3", "flac", "aac", "ogg", "opus"], min_length=1, max_length=20
    )
    source_order: list[str] = Field(default=["mam", "prowlarr"], min_length=1, max_length=100)
    criteria: list[Literal["format", "source", "seeders"]] = Field(
        default=["format", "source", "seeders"], min_length=3, max_length=3
    )
    blocked_formats: list[str] = Field(default_factory=list, max_length=20)
    maximum_bytes: int | None = Field(default=None, gt=0, le=2**53 - 1)

    @field_validator("ebook_formats", "audio_formats", "blocked_formats")
    @classmethod
    def formats(cls, values, info: ValidationInfo):
        normalized = [value.strip().lower().lstrip(".") for value in values]
        allowed = {
            "ebook_formats": {"epub", "pdf", "mobi", "azw", "azw3", "cbz", "cbr"},
            "audio_formats": {"m4b", "mp3", "flac", "aac", "ogg", "opus"},
        }.get(info.field_name, FORMATS)
        if len(set(normalized)) != len(normalized) or not set(normalized) <= allowed:
            raise ValueError("Use distinct supported format names")
        return normalized

    @field_validator("criteria")
    @classmethod
    def order(cls, values):
        if set(values) != {"format", "source", "seeders"}:
            raise ValueError("Include format, source and seeders once each")
        return values

    @field_validator("source_order")
    @classmethod
    def sources(cls, values):
        if len(set(values)) != len(values) or any(
            not re.fullmatch(r"mam|prowlarr(?::[1-9][0-9]{0,9})?", v) for v in values
        ):
            raise ValueError("Use distinct source names or Prowlarr indexer references")
        return values


class ProfileSnapshot(BaseModel):
    id: UUID | None = None
    generation: int = 0
    name: str = "Balanced"
    preferences: ReleasePreferences


async def profile_snapshot(db, user_id, identifier=None, generation=None):
    if identifier is None:
        if generation not in (None, 0):
            raise HTTPException(422, "Choose a saved profile before specifying its revision")
        return ProfileSnapshot(preferences=ReleasePreferences())
    row = await db.scalar(
        select(AcquisitionProfile).where(
            AcquisitionProfile.id == identifier, AcquisitionProfile.owner_id == user_id
        )
    )
    if not row:
        raise HTTPException(404, "Acquisition profile not found")
    if generation is not None and row.generation != generation:
        raise HTTPException(409, "This acquisition profile changed. Refresh the preferences.")
    return ProfileSnapshot(
        id=row.id, generation=row.generation, name=row.name, preferences=row.preferences
    )


def normalized(value):
    return " ".join(
        re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", value).casefold()).split()
    )


class ReleaseAssessment(BaseModel):
    identity: Literal["corroborated", "possible", "unmatched"]
    blocked: list[str]
    review: list[str]
    explanation: list[str]
    formats: list[str]
    source_origin: str


def assess_release(release, work, preferences, medium="all"):
    title, expected = (
        normalized(getattr(release, "title", release.raw_title)),
        normalized(work["title"]),
    )
    authors = {normalized(a) for a in release.authors}
    work_authors = {normalized(a) for a in work["authors"]}
    identity = (
        "corroborated"
        if title == expected and authors & work_authors
        else "possible"
        if title == expected or (expected and expected in title)
        else "unmatched"
    )
    if authors and work_authors and not authors & work_authors:
        identity = "unmatched"
    blocked, review, explanation = [], [], []
    if identity != "corroborated":
        review.append("Confirm this release contains the selected title and author")
    else:
        explanation.append(
            "Source title and author agree with the catalog; file identity still needs inspection"
        )
    if release.protocol != "torrent" or getattr(release, "acquisition_supported", True) is False:
        blocked.append("No supported torrent-file acquisition is available")
    if medium != "all" and release.medium is not None and medium != release.medium:
        blocked.append("The release is for a different medium")
    if release.medium is None:
        review.append("The source does not identify the medium")
    formats = sorted({f.lower() for f in release.formats})
    forbidden = set(formats) & set(preferences.blocked_formats)
    if forbidden:
        blocked.append("Blocked format: " + ", ".join(sorted(forbidden)))
    if not formats:
        review.append("File formats are unknown until torrent or file inspection")
    if preferences.maximum_bytes is not None:
        if release.size_bytes is None:
            review.append("Transfer size is unknown")
        elif release.size_bytes > preferences.maximum_bytes:
            blocked.append("Transfer exceeds the profile size limit")
    origin = release.source + (":" + release.indexer_id if release.indexer_id else "")
    preferred = (
        preferences.audio_formats if release.medium == "audio" else preferences.ebook_formats
    )
    matched = [f for f in preferred if f in formats]
    explanation.append("Preferred format: " + (matched[0] if matched else "not established"))
    explanation.append("Source: " + origin)
    explanation.append(
        f"{release.seeders} reported seeders"
        if release.seeders is not None
        else "Seed count unknown"
    )
    return ReleaseAssessment(
        identity=identity,
        blocked=blocked,
        review=review,
        explanation=explanation,
        formats=formats,
        source_origin=origin,
    )


def ranking_key(release, assessment, preferences):
    preferred = (
        preferences.audio_formats if release.medium == "audio" else preferences.ebook_formats
    )
    format_rank = min(
        (preferred.index(f) for f in assessment.formats if f in preferred), default=len(preferred)
    )
    origin = assessment.source_origin
    source_rank = (
        preferences.source_order.index(origin)
        if origin in preferences.source_order
        else preferences.source_order.index(release.source)
        if release.source in preferences.source_order
        else len(preferences.source_order)
    )
    scores = {
        "format": (format_rank,),
        "source": (source_rank,),
        "seeders": (release.seeders is None, -(release.seeders or 0)),
    }
    # Identity/capability checks precede preferences; no seed count can rescue a wrong book.
    return (
        bool(assessment.blocked),
        {"corroborated": 0, "possible": 1, "unmatched": 2}[assessment.identity],
        *(scores[c] for c in preferences.criteria),
        origin,
        release.source_id,
    )


def enforce_profile(release, descriptor, snapshot):
    preferences = snapshot.preferences
    actual_formats = {
        p.path.rsplit(".", 1)[-1].lower() for p in descriptor.files if "." in p.path
    } & FORMATS
    forbidden = (set(release.formats) | actual_formats) & set(preferences.blocked_formats)
    if forbidden:
        raise HTTPException(
            422, "The selected torrent contains a blocked format: " + ", ".join(sorted(forbidden))
        )
    if (
        preferences.maximum_bytes is not None
        and descriptor.torrent_bytes > preferences.maximum_bytes
    ):
        raise HTTPException(422, "The inspected torrent exceeds the profile size limit")


def enforce_inspected_profile(files, snapshot):
    """Recheck the whole observed transfer, including excluded children and companions."""
    preferences = snapshot.preferences
    forbidden = {file["extension"] for file in files} & set(preferences.blocked_formats)
    if forbidden:
        raise HTTPException(
            422, "The downloaded files contain a blocked format: " + ", ".join(sorted(forbidden))
        )
    if (
        preferences.maximum_bytes is not None
        and sum(file["identity"]["size"] for file in files) > preferences.maximum_bytes
    ):
        raise HTTPException(422, "The downloaded files exceed the frozen profile size limit")
