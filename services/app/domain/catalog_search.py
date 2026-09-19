"""Local title, series and identifier predicates within a visible work origin."""

import re

from sqlalchemy import Text, case, cast, exists, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import CatalogSeries, SeriesMembership, Version, WorkMetadataSource
from app.importing.match_evidence import ISBN_KEYS, identifier, isbn_forms


def local_match(user, origin, query):
    query = query.strip()
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    matches = [origin.title.ilike(pattern), cast(origin.authors, Text).ilike(pattern)]
    # Expand only the declared series names, never arbitrary snapshot text.
    series = WorkMetadataSource.snapshot["series"]
    entries = func.jsonb_array_elements(
        case((func.jsonb_typeof(series) == "array", series), else_=cast(literal("[]"), JSONB))
    ).table_valued("value")
    name = cast(entries.c.value, JSONB)["name"].astext
    matches.append(
        exists(
            select(WorkMetadataSource.id)
            .join(entries, true())
            .where(
                WorkMetadataSource.work_id == origin.id,
                WorkMetadataSource.accepted.is_(True),
                name.ilike(pattern),
            )
        )
    )
    matches.append(
        exists(
            select(SeriesMembership.id)
            .join(CatalogSeries)
            .where(
                SeriesMembership.work_id == origin.id,
                SeriesMembership.present.is_(True),
                CatalogSeries.owner_id == user.id,
                CatalogSeries.fetched_at.is_not(None),
                CatalogSeries.name.ilike(pattern),
            )
        )
    )
    found = identifier("", query)
    if not found:
        found = identifier("asin", query)
    if found:
        scheme, value = found
        keys = ISBN_KEYS if scheme == "isbn" else ("asin",)
        forms = isbn_forms(value) if scheme == "isbn" else {value}
        values = []
        for key in keys:
            stored = func.upper(Version.identifiers[key].astext)
            stored = func.regexp_replace(
                stored, r"^(URN:)?(?:ISBN(?:[-_ ]?(?:10|13))?|ASIN)\s*:\s*", "", "i"
            )
            values.append(func.regexp_replace(stored, r"[\s-]", "", "g").in_(forms))
        matches.append(exists(select(Version.id).where(Version.work_id == origin.id, or_(*values))))
    qualified = re.fullmatch(r"(hardcover|openlibrary):\s*(\S+)", query, re.I)
    if qualified:
        provider, external_id = qualified.groups()
        matches.append(
            exists(
                select(WorkMetadataSource.id).where(
                    WorkMetadataSource.work_id == origin.id,
                    WorkMetadataSource.accepted.is_(True),
                    WorkMetadataSource.provider == provider.lower(),
                    func.lower(WorkMetadataSource.external_id) == external_id.lower(),
                )
            )
        )
    return or_(*matches)
