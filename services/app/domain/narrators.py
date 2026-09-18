"""Conservative narrator-name preferences, never recording identity."""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field


def display_name(value):
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not value or any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Use a nonempty narrator name without control characters")
    return value


def name_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def distinct_names(values):
    seen, result = set(), []
    for value in values:
        key = name_key(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


NarratorNames = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200), AfterValidator(display_name)]],
    Field(max_length=32),
    AfterValidator(distinct_names),
]


def accepts(required, observed):
    return {name_key(value) for value in required}.issubset(
        {name_key(value) for value in observed or []}
    )


def preference_rank(preferred, observed):
    names = {name_key(value) for value in observed or []}
    return next(
        (i for i, value in enumerate(preferred) if name_key(value) in names), len(preferred)
    )


def combined(left, right):
    return sorted(distinct_names([*left, *right]), key=name_key)


def embedded_names(value):
    """Only explicit semicolon-separated credits; commas can be part of a name."""
    return sorted({name_key(part) for part in value.split(";") if part.strip()})
