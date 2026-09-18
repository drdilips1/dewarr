"""Explainable release preferences, separate from bibliographic identity and ownership."""

import re
import unicodedata
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_serializer
from sqlalchemy import and_, literal, select
from sqlalchemy.orm import aliased

from app.db.models import AcquisitionDefaults, AcquisitionProfile
from app.importing.naming import fingerprint

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


DEFAULTS_LOCK = "acquisition-preferences"


def sparse_schema(schema):
    for field in schema.get("properties", {}).values():
        field.pop("default", None)


class PreferenceOverrides(ReleasePreferences):
    """Omitted fields inherit; explicit empty block lists and null limits override."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=sparse_schema)

    @model_serializer(mode="wrap")
    def sparse(self, handler):
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class ProfileSnapshot(BaseModel):
    id: UUID | None = None
    generation: int = 0
    name: str = "Balanced"
    preferences: ReleasePreferences
    overrides: PreferenceOverrides = Field(default_factory=PreferenceOverrides)
    origins: dict[str, str] = Field(default_factory=dict)
    effective_revision: str | None = None
    base_effective_revision: str | None = None
    list_overrides: PreferenceOverrides | None = None
    request_overrides: PreferenceOverrides | None = None


def resolve_preferences(layers):
    values = ReleasePreferences().model_dump()
    origins = dict.fromkeys(values, "Built-in default")
    for label, overrides in layers:
        sparse = PreferenceOverrides.model_validate(overrides).model_dump()
        values.update(sparse)
        origins.update(dict.fromkeys(sparse, label))
    return ReleasePreferences.model_validate(values), origins


async def default_layers(db, user_id=None):
    keys = ["installation", f"user:{user_id}"] if user_id else ["installation"]
    rows = {
        row.key: row
        for row in await db.scalars(
            select(AcquisitionDefaults)
            .where(AcquisitionDefaults.key.in_(keys))
            .execution_options(populate_existing=True)
        )
    }
    return [
        (
            "Installation default" if key == "installation" else "Personal default",
            rows[key].preferences,
        )
        for key in keys
        if key in rows
    ]


async def profile_snapshot(db, user_id, identifier=None, generation=None, expected_revision=None):
    # Read all layers in one MVCC statement. Read-side advisory locks would be
    # held across caller transactions and invert list/work/configuration locks.
    # Settings writers retain their own serialization and revision checks; each
    # acquisition freezes this observed policy and revalidates before dispatch.
    installation = aliased(AcquisitionDefaults)
    personal = aliased(AcquisitionDefaults)
    saved = aliased(AcquisitionProfile)
    anchor = select(literal(1).label("anchor")).subquery()
    row = (
        await db.execute(
            select(
                installation.preferences.label("installation"),
                personal.preferences.label("personal"),
                saved.id,
                saved.generation,
                saved.name,
                saved.preferences,
            )
            .select_from(anchor)
            .outerjoin(installation, installation.key == "installation")
            .outerjoin(personal, personal.key == f"user:{user_id}")
            .outerjoin(saved, and_(saved.id == identifier, saved.owner_id == user_id))
        )
    ).one()
    layers = [
        (label, values)
        for label, values in [
            ("Installation default", row.installation),
            ("Personal default", row.personal),
        ]
        if values is not None
    ]
    if identifier is None:
        if generation not in (None, 0):
            raise HTTPException(422, "Choose a saved profile before specifying its revision")
    else:
        if row.id is None:
            raise HTTPException(404, "Acquisition profile not found")
        if generation is not None and row.generation != generation:
            raise HTTPException(409, "This acquisition profile changed. Refresh the preferences.")
        layers.append(("Profile", row.preferences))
    preferences, origins = resolve_preferences(layers)
    revision = fingerprint(
        {
            "id": str(identifier) if identifier else None,
            "generation": row.generation if row.id else 0,
            "preferences": preferences.model_dump(),
            "origins": origins,
        }
    )
    if expected_revision is not None and expected_revision != revision:
        raise HTTPException(409, "Effective download preferences changed. Refresh the preferences.")
    return ProfileSnapshot(
        id=row.id,
        generation=row.generation if row.id else 0,
        name=row.name if row.id else "Balanced",
        preferences=preferences,
        overrides=PreferenceOverrides.model_validate(row.preferences if row.id else {}),
        origins=origins,
        effective_revision=revision,
        base_effective_revision=revision,
    )


def overlay_profile(profile, *, list_overrides=None, request_overrides=None):
    values = profile.preferences.model_dump()
    origins = dict(profile.origins)
    for label, overrides in [
        ("List override", list_overrides),
        ("Request override", request_overrides),
    ]:
        if overrides is not None:
            sparse = PreferenceOverrides.model_validate(overrides).model_dump()
            values.update(sparse)
            origins.update(dict.fromkeys(sparse, label))
    return profile.model_copy(
        update={
            "preferences": ReleasePreferences.model_validate(values),
            "origins": origins,
            "list_overrides": PreferenceOverrides.model_validate(list_overrides)
            if list_overrides
            else None,
            "request_overrides": PreferenceOverrides.model_validate(request_overrides)
            if request_overrides
            else None,
            "base_effective_revision": profile.base_effective_revision
            or profile.effective_revision,
            "effective_revision": fingerprint(
                {
                    "id": str(profile.id) if profile.id else None,
                    "generation": profile.generation,
                    "preferences": values,
                    "origins": origins,
                }
            ),
        }
    )


async def refresh_profile(db, user_id, snapshot):
    base = await profile_snapshot(db, user_id, snapshot.id, snapshot.generation)
    return overlay_profile(
        base, list_overrides=snapshot.list_overrides, request_overrides=snapshot.request_overrides
    )


def same_profile(current, frozen):
    # Old receipts lack provenance. Their actual frozen policy remains authoritative.
    return (current.id, current.generation, current.preferences) == (
        frozen.id,
        frozen.generation,
        frozen.preferences,
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
