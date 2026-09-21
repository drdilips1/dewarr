"""Normalize presentation-only title labels without discarding actual subtitles."""

import re
import unicodedata

from sqlalchemy import func, literal_column

# A repeated trailing chain makes the order of edition labels irrelevant. The
# same expression runs in Python and PostgreSQL; never strip arbitrary brackets.
EDITION_LABEL = (
    r"\s*(?::\s*|\(\s*)(?:a novel|reese['’]s book club(?: pick)?|"
    r"oprah['’]s book club(?: pick)?)[\s)]*"
)
VERSION_LABEL = (
    r"\s*\(\s*(?:unabridged|abridged|older version|original recording|"
    r"revised edition|anniversary edition)\s*\)\s*"
)
NARRATOR_LABEL = r"\s*\(\s*(?:read|narrated)\s+by\s+([^()]+)\)\s*"
DISPLAY_SUFFIX = rf"(?:{EDITION_LABEL}|{VERSION_LABEL}|{NARRATOR_LABEL})+$"

# These describe different content, not merely an edition of the short title.
# Keep this guard shared between display grouping and provider matching.
DISTINCT_SUBTITLE = (
    r":\s*(?:(?:a|an|the)\s+)?(?:book|volume|vol\.?|part|summary|study guide|"
    r"workbook|companion|sequel|dramatized|adaptation|graphic novel|box set|omnibus)"
)


def distinct_work_subtitle(value):
    return bool(re.search(DISTINCT_SUBTITLE + r"\b", value, re.IGNORECASE))


def title_narrators(value):
    suffix = re.search(DISPLAY_SUFFIX, value or "", re.IGNORECASE)
    if not suffix:
        return []
    return [
        " ".join(match.group(1).split())
        for match in re.finditer(NARRATOR_LABEL, suffix.group(), re.IGNORECASE)
    ]


def display_text(value):
    value = unicodedata.normalize("NFKC", value).lower().translate(str.maketrans("‘’", "''"))
    return " ".join(value.split())


def display_text_sql(value):
    value = func.translate(func.lower(func.normalize(value, literal_column("NFKC"))), "‘’", "''")
    return func.trim(func.regexp_replace(value, r"\s+", " ", "g"))


def display_title(value):
    value = display_text(value)
    return re.sub(DISPLAY_SUFFIX, "", value).strip()


def display_title_sql(value):
    value = display_text_sql(value)
    return func.trim(func.regexp_replace(value, DISPLAY_SUFFIX, "", "g"))
