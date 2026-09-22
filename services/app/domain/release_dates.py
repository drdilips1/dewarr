"""Release-day precedence for upcoming books.

A full audiobook street date wins. A work date is shown as the work date and
the audiobook day stays unknown. A year is not a day, and two dates are never
averaged.
"""

from datetime import date, datetime, timedelta

GENRES = (
    "fantasy",
    "science-fiction",
    "romance",
    "mystery",
    "horror",
    "historical-fiction",
    "non-fiction",
    "history",
    "biography",
    "young-adult",
    "children",
)

_ALIASES = {
    "sci-fi": "science-fiction",
    "scifi": "science-fiction",
    "sciencefiction": "science-fiction",
    "sf": "science-fiction",
    "space-opera": "science-fiction",
    "spaceopera": "science-fiction",
    "ya": "young-adult",
    "youngadult": "young-adult",
    "nonfiction": "non-fiction",
    "hist-fic": "historical-fiction",
    "historicalfiction": "historical-fiction",
    "kids": "children",
    "childrens": "children",
}
_SUFFIXES = (
    ("-fantasy", "fantasy"),
    ("-science-fiction", "science-fiction"),
    ("-romance", "romance"),
    ("-mystery", "mystery"),
    ("-horror", "horror"),
)

_BASIS = {"audiobook": 2, "work": 1, "unknown": 0}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def genre_slug(value):
    if not isinstance(value, str):
        return None
    text = "-".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    compact = text.replace("-", "")
    slug = _ALIASES.get(text) or _ALIASES.get(compact) or text
    if slug in GENRES:
        return slug
    # "Dark Fantasy" and "Hard Science Fiction" are shelves of a tracked genre.
    for suffix, genre in _SUFFIXES:
        if slug.endswith(suffix):
            return genre
    return None


def parse_iso_day(value):
    """A calendar day needs a year, month, and day. A year or month is not a day."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_prose_day(value):
    if not isinstance(value, str):
        return None
    parts = value.replace(",", " ").split()
    if len(parts) != 3:
        return None
    month = _MONTHS.get(parts[0].casefold())
    if not month or not parts[1].isdigit() or not parts[2].isdigit() or len(parts[2]) != 4:
        return None
    try:
        return date(int(parts[2]), month, int(parts[1]))
    except ValueError:
        return None


def choose_release(*, libro=None, audio=None, work=None):
    """Pick one day. Precedence is the audiobook page, then the audio edition, then the work."""
    libro_day = parse_iso_day(libro)
    if libro_day:
        return libro_day, "audiobook"
    audio_day = parse_iso_day(audio)
    if audio_day:
        return audio_day, "audiobook"
    work_day = parse_iso_day(work)
    if work_day:
        return work_day, "work"
    return None, "unknown"


def audiobook_date_label(basis):
    return "audiobook" if basis == "audiobook" else "unknown"


def search_allowed(day, today, *, coming_soon=False):
    """Scene copies often exist before the retail date. Do not search until that day."""
    if day and day > today:
        return False
    if coming_soon and day is None:
        return False
    return True


def release_facts(fields):
    raw = (fields or {}).get("release") or {}
    if not isinstance(raw, dict):
        raw = {}
    basis = raw.get("basis") if raw.get("basis") in _BASIS else "unknown"
    return parse_iso_day(raw.get("date")), basis, bool(raw.get("coming_soon"))


def assign_release(fields, day, basis, *, coming_soon=False, source, extra=None):
    """Store one resolved day. A stronger audiobook date is not replaced by a work date."""
    current_fields = dict(fields or {})
    current = dict(current_fields.get("release") or {})
    incoming = parse_iso_day(day) if not isinstance(day, date) else day
    current_day = parse_iso_day(current.get("date"))
    current_basis = current.get("basis") if current.get("basis") in _BASIS else "unknown"
    if (
        current_day
        and incoming
        and _BASIS[current_basis] > _BASIS.get(basis, 0)
        and not (source == "librofm" and basis == "audiobook")
    ):
        return current_fields
    if source != "librofm" and current.get("source") == "librofm" and current_basis == "audiobook":
        if current_day:
            return current_fields
    release = {
        **current,
        "date": incoming.isoformat() if incoming else None,
        "basis": basis if incoming or basis == "unknown" else basis,
        "coming_soon": bool(coming_soon)
        if incoming
        else bool(coming_soon or current.get("coming_soon")),
        "source": source,
    }
    if not incoming:
        release["date"] = current_day.isoformat() if current_day else None
        release["basis"] = current_basis if current_day else "unknown"
    if extra:
        for key, value in extra.items():
            if value:
                release[key] = value
    current_fields["release"] = release
    return current_fields


def filter_discover(items, genres):
    """An empty genre selection is no discover overlay. Followed books are not passed here."""
    selected = [genre for genre in genres if genre in GENRES]
    if not selected:
        return []
    chosen = set(selected)
    return [item for item in items if chosen & set(item.get("genres") or [])]


def replaces_release(current_day, current_basis, incoming_day, incoming_basis):
    """An audiobook day replaces a missing day or a work day. It does not move an equal day."""
    incoming = (
        incoming_day
        if isinstance(incoming_day, date) and not isinstance(incoming_day, datetime)
        else parse_iso_day(incoming_day)
    )
    if incoming is None:
        return False
    current = (
        current_day
        if isinstance(current_day, date) and not isinstance(current_day, datetime)
        else parse_iso_day(current_day)
    )
    if current is None:
        return True
    return _BASIS.get(incoming_basis, 0) > _BASIS.get(current_basis, 0)


def _release_rank(item):
    basis = item.get("basis") if item.get("basis") in _BASIS else "unknown"
    return (1 if item.get("release_date") else 0, _BASIS[basis])


def _absorb(target, item):
    target["followed"] = bool(target.get("followed") or item.get("followed"))
    target["in_library"] = bool(target.get("in_library") or item.get("in_library"))
    if item.get("work_id") and not target.get("work_id"):
        target["work_id"] = item["work_id"]
    if item.get("external_id") and not target.get("external_id"):
        target["external_id"] = item["external_id"]
    if item.get("genres") and not target.get("genres"):
        target["genres"] = item["genres"]
    if item.get("state") and not target.get("state"):
        target["state"] = item["state"]
    if _release_rank(item) <= _release_rank(target):
        return
    target["release_date"] = item.get("release_date")
    target["basis"] = item.get("basis") or target.get("basis")
    if item.get("cover_url") and not target.get("cover_url"):
        target["cover_url"] = item["cover_url"]


def merge_month(personal, discover, genres):
    """Followed and library books stay on the grid even when they are outside the genre filter.

    A later audiobook day replaces an undated follow or a work day for the same book.
    """
    overlay = filter_discover(discover, genres)
    by_key = {}
    items = []
    for item in [*personal, *overlay]:
        keys = []
        if item.get("work_id"):
            keys.append(("work", str(item["work_id"])))
        if item.get("external_id"):
            keys.append(("ext", str(item["external_id"])))
        current = next((by_key[key] for key in keys if key in by_key), None)
        if current is None:
            for key in keys:
                by_key[key] = item
            items.append(item)
            continue
        _absorb(current, item)
        for key in keys:
            by_key[key] = current
        if current.get("work_id"):
            by_key[("work", str(current["work_id"]))] = current
        if current.get("external_id"):
            by_key[("ext", str(current["external_id"]))] = current
    return items


def month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def due_action(
    *,
    state,
    release_date,
    today,
    now,
    next_check_at,
    owned,
    in_flight,
    failed,
):
    """Hold until release day, then search. A profile miss retries and does not download."""
    if state in {"stopped", "available"}:
        return "idle"
    if owned:
        return "available"
    if release_date is None or release_date > today:
        return "hold"
    if state == "waiting":
        return "resume" if next_check_at is None or next_check_at <= now else "hold"
    if in_flight:
        return "wait"
    if next_check_at and next_check_at > now:
        return "wait"
    if failed:
        return "search"
    return "wait"


def retry_at(round_number, now):
    from app.domain.list_automation import retry_at as schedule_retry

    return schedule_retry(round_number, now)
