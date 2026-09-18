"""Invented MAM response; no tracker account, passkey or downloaded media."""


def release_row(**changes):
    return {
        "id": 501,
        "title": "Harbor &amp; Roads — Complete Stories",
        "main_cat": 13,
        "catname": "Audiobooks - Fiction",
        "author_info": '{"1":"Alex Morgan"}',
        "narrator_info": '{"2":"Jordan Lee"}',
        "series_info": '{"7":["Harbor Stories","1-3"]}',
        "language": 1,
        "lang_code": "en",
        "size": "1.25 GiB",
        "filetype": "M4B / MP3",
        "seeders": 42,
        "leechers": 0,
        "times_completed": 321,
        "free": 1,
        "vip": 0,
        "added": "2026-09-01 12:00:00",
        "description": "<p>An invented three-book collection.</p><script>unsafe()</script>"
        "<p>Narrated by Jordan Lee.</p>",
        "tags": ["Fiction", "Adventure"],
        "isbn": "9781234567897",
        "mediainfo": "Audio: AAC; duration: 12 hours",
        "dl": "fixture-private-download-token",
        **changes,
    }


def search_response(**changes):
    return {"data": [release_row()], "found": 1, "total": 1, **changes}
