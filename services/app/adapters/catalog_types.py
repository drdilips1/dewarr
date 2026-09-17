import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

Provider = Literal["hardcover", "openlibrary"]


def year(value) -> int | None:
    matches = re.findall(r"\b([12]\d{3})\b", str(value or ""))
    return int(matches[0]) if len(matches) == 1 else None


def cover_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        # Only known image hosts; untrusted provider URLs never become arbitrary requests.
        if (
            url.scheme == "https"
            and not url.username
            and not url.password
            and (host == "covers.openlibrary.org" or host == "assets.hardcover.app")
        ):
            return value
    except ValueError:
        pass
    return None


class EditionData(BaseModel):
    external_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=600)
    medium: Literal["ebook", "audio", "print", "unknown"] = "unknown"
    language: str | None = Field(default=None, max_length=20)
    narrators: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    publisher: str | None = None
    description: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    cover_url: str | None = None
    abridged: bool | None = None


class SeriesData(BaseModel):
    external_id: str
    name: str
    position: str | None = None
    compilation: bool = False


class BookData(BaseModel):
    provider: Provider
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=600)
    authors: list[str] = Field(default_factory=list, max_length=100)
    description: str | None = None
    publication_year: int | None = None
    language: str | None = None
    cover_url: str | None = None
    subjects: list[str] = Field(default_factory=list)
    editions: list[EditionData] = Field(default_factory=list)
    editions_more: bool = False
    editions_offset: int = 0
    series: list[SeriesData] = Field(default_factory=list)
    canonical_id: str | None = None

    @field_validator("authors")
    @classmethod
    def names(cls, value):
        return list(dict.fromkeys(" ".join(name.split()) for name in value if name.strip()))


class SearchPage(BaseModel):
    provider: Provider
    items: list[BookData]
    page: int
    has_more: bool
    stale: bool = False
    warning: str | None = None
