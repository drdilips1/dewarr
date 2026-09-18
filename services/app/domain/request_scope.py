"""Inheritable acquisition choices; resolved requests remain strict and immutable."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.domain.narrators import NarratorNames


def language(value):
    if not value:
        return None
    parts = value.casefold().replace("_", "-").split("-")
    parts[0] = {
        "eng": "en",
        "fra": "fr",
        "fre": "fr",
        "deu": "de",
        "ger": "de",
        "spa": "es",
        "ita": "it",
        "por": "pt",
        "jpn": "ja",
    }.get(parts[0], parts[0])
    return "-".join(parts)


class ScopePreferences(BaseModel):
    desired_media: Literal["ebook", "audio", "both", "either"] | None = None
    preferred_medium: Literal["ebook", "audio"] = "audio"
    language: str | None = Field(
        default=None, pattern=r"^[a-zA-Z]{2,3}([-_][a-zA-Z0-9]{2,8})*$", max_length=20
    )
    abridged: bool | None = None
    required_narrators: NarratorNames = Field(default_factory=list)
    standalone: bool = False
    ebook_library_id: UUID | None = None
    audio_library_id: UUID | None = None

    @field_validator("language")
    @classmethod
    def canonical_language(cls, value):
        return language(value)


SCOPE_FIELDS = {
    "mode": "desired_media",
    "preferred_medium": "preferred_medium",
    "language": "language",
    "abridged": "abridged",
    "required_narrators": "required_narrators",
    "standalone": "standalone",
    "ebook_library_id": "ebook_library_id",
    "audio_library_id": "audio_library_id",
}


def overrides(options):
    """Explicit options beat same-level preferences; omitted options inherit."""
    values = options.model_dump(mode="json", exclude_unset=True)
    return {
        preference: values[field]
        for field, preference in SCOPE_FIELDS.items()
        if field in values and not (field == "preferred_medium" and values[field] is None)
    }


def specification(options, profile):
    from app.domain.acquisition import RequestSpec

    preferences = profile.preferences.model_dump(mode="json")
    values = {field: preferences[name] for field, name in SCOPE_FIELDS.items()}
    origins = {
        field: profile.origins.get(name, "Saved policy") for field, name in SCOPE_FIELDS.items()
    }
    explicit = options.model_dump(mode="json", exclude_unset=True)
    values.update(explicit)
    # Defaults for the other medium remain usable for future requests, but do
    # not become contradictory constraints when this request chooses one medium.
    inactive = ["preferred_medium"] if values["mode"] != "either" else []
    if values["mode"] == "ebook":
        inactive.extend(["audio_library_id", "abridged", "required_narrators"])
    if values["mode"] == "audio":
        inactive.append("ebook_library_id")
    for field in inactive:
        if field not in explicit:
            values[field] = [] if field == "required_narrators" else None
            origins[field] = "Not applicable"
    try:
        result = RequestSpec.model_validate(values)
    except ValidationError as error:
        message = (
            "Choose media to request or set a default"
            if values["mode"] is None
            else "Request scope is inconsistent; review media, language and library choices"
        )
        raise HTTPException(422, message) from error
    return result, origins


def same_command(saved, current):
    """Replay pre-inheritance commands under their original explicit defaults."""
    if not isinstance(saved, dict):
        return False
    if saved == current:
        return True
    if "scope_inheritance" in saved or current.get("scope_inheritance") != 1:
        return False
    from app.domain.acquisition import RequestSpec

    try:
        expanded = RequestSpec.model_validate(current["specification"]).model_dump(mode="json")
    except ValidationError:
        return False
    legacy = {key: value for key, value in current.items() if key != "scope_inheritance"}
    legacy["specification"] = expanded
    return saved == legacy


def sparse_schema(schema):
    for field in schema.get("properties", {}).values():
        field.pop("default", None)
