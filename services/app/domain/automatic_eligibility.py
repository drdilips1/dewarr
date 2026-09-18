"""Automatic candidate eligibility. Tracker claims never establish library ownership."""

import re
from pathlib import PurePosixPath

from app.domain.acquisition import language_accepts
from app.domain.release_profiles import assess_release, normalized
from app.importing.match_evidence import isbn_forms

EBOOKS = {"epub", "pdf", "cbz"}
AUDIO = {"m4b", "mp3", "flac", "aac", "ogg", "opus"}
SIDECARS = {"jpg", "jpeg", "png", "webp", "opf", "nfo", "txt", "cue", "m3u"}
PARTIAL = re.compile(r"\b(sample|excerpt|preview|incomplete|truncated)\b", re.I)
PACK = re.compile(
    r"\b(omnibus|box[ -]?set|anthology|complete series|books?\s+\d+\s*[-–]\s*\d+)\b", re.I
)
DEFAULT_MAXIMUM = {"ebook": 1024**3, "audio": 10 * 1024**3}


def limit_bytes(preferences, medium):
    return preferences.maximum_bytes or DEFAULT_MAXIMUM[medium]


def eligibility(release, work, rule, preferences, *, version=None, descriptor=None):
    assessment = assess_release(release, work, preferences, rule["medium"])
    reasons = list(assessment.blocked)
    if assessment.identity != "corroborated":
        reasons.append("The source must corroborate the catalog title and author")
    if release.medium != rule["medium"]:
        reasons.append("The source must identify the requested medium")
    required_language = rule["language"] or (version.language if version else None)
    if not language_accepts(required_language, release.language):
        reasons.append("The source does not confirm the required language")
    if release.seeders is None or release.seeders == 0:
        reasons.append("At least one reported seeder is required for automatic selection")
    text = " ".join(
        [release.raw_title, getattr(release, "title", ""), *getattr(release, "tags", [])]
    )
    if PARTIAL.search(text):
        reasons.append("The source labels this release as partial content")
    if (
        PACK.search(text)
        or len(release.coverage) > 1
        or any(
            re.search(r"\d\s*[-–,/]\s*\d", series.position or "")
            for series in getattr(release, "series", [])
        )
    ):
        reasons.append("Collection coverage needs review before automatic selection")
    if rule["abridged"] is not None:
        # Exact source tags are claims; narration duration or prose is not an abridgment flag.
        tags = {normalized(tag) for tag in getattr(release, "tags", [])}
        expected = "abridged" if rule["abridged"] else "unabridged"
        opposite = "unabridged" if rule["abridged"] else "abridged"
        if expected not in tags or opposite in tags:
            reasons.append("The source does not confirm the required abridgment")
    if version:
        if version.medium == "audio":
            reasons.append(
                "Exact recording identity requires review; narrator names alone are insufficient"
            )
        else:
            expected = set().union(
                *(
                    isbn_forms(v)
                    for k, values in version.identifiers.items()
                    if k.lower() in {"isbn", "isbn10", "isbn13", "isbn_10", "isbn_13"}
                    for v in (values if isinstance(values, list) else [values])
                )
            )
            observed = isbn_forms(getattr(release, "isbn", None) or "")
            if not expected or not expected.intersection(observed):
                reasons.append("The source does not corroborate the selected edition's ISBN")
    ceiling = limit_bytes(preferences, rule["medium"])
    if release.size_bytes is not None and release.size_bytes > ceiling:
        reasons.append("Reported transfer size exceeds the automatic selection limit")
    if descriptor:
        if descriptor.content_bytes > ceiling:
            reasons.append("Inspected transfer size exceeds the automatic selection limit")
        formats = {PurePosixPath(f.path).suffix.lower().lstrip(".") for f in descriptor.files}
        if formats & set(preferences.blocked_formats):
            reasons.append("The inspected torrent contains a blocked format")
        supported = EBOOKS if rule["medium"] == "ebook" else AUDIO
        primary = [
            f
            for f in descriptor.files
            if PurePosixPath(f.path).suffix.lower().lstrip(".") in supported
        ]
        allowed = supported | SIDECARS | ({"pdf"} if rule["medium"] == "audio" else set())
        if formats - allowed:
            reasons.append("The torrent contains unsupported or ambiguous file types")
        if not primary:
            reasons.append("No supported primary media files were found")
        elif rule["medium"] == "ebook" and len(primary) != 1:
            reasons.append("Multiple ebook files need edition or collection review")
        elif rule["medium"] == "audio":
            if len(primary) > 500 or len({str(PurePosixPath(f.path).parent) for f in primary}) != 1:
                reasons.append(
                    "Audio files span multiple book folders or exceed the automatic track limit"
                )
            if len({PurePosixPath(f.path).suffix.lower() for f in primary}) != 1:
                reasons.append("Alternative audio encodings need recording review")
            if len(primary) > 1:
                stems = [normalized(PurePosixPath(f.path).stem) for f in primary]
                book_title = normalized(work["title"])
                if any(
                    not re.fullmatch(
                        r"(?:(?:disc|cd|part)\s*\d+\s*)?(?:(?:track|chapter)\s*)?\d+",
                        stem.removeprefix(book_title).strip(),
                    )
                    for stem in stems
                ):
                    reasons.append("Audio filenames do not establish one numbered track sequence")
        if PACK.search(descriptor.name) or any(PACK.search(f.path) for f in primary):
            reasons.append("The file manifest indicates a collection requiring coverage review")
        if any(PARTIAL.search(f.path) for f in primary):
            reasons.append("The file manifest indicates partial content")
        preferred = (
            preferences.ebook_formats if rule["medium"] == "ebook" else preferences.audio_formats
        )
        if not formats.intersection(preferred):
            reasons.append("No preferred media format is present in the torrent")
        if not (
            (len(descriptor.files) == 1 and "/" not in descriptor.files[0].path)
            or all(f.path.startswith(descriptor.name + "/") for f in descriptor.files)
        ):
            reasons.append("The torrent does not have one supported import root")
    elif release.formats and not set(release.formats) & (
        EBOOKS if rule["medium"] == "ebook" else AUDIO
    ):
        reasons.append("Reported formats are not supported by the automatic importer")
    return list(dict.fromkeys(reasons))
