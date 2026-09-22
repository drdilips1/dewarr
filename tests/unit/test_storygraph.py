from urllib.parse import parse_qsl

import httpx
import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.storygraph import (
    Target,
    cookies,
    discover,
    list_url,
    page_title,
    parse_records,
    parse_tags,
    read_list,
    retarget_config,
    username_from,
)

HARBOR = "f3158a48-cb26-4887-a8df-9b8cae6cc377"
QUEUE = "11111111-1111-4111-8111-111111111111"
TAG = "9d7e824e-e4d8-40b1-8fef-6d6b5a6a44ba"
SECRET = {"session_cookie": "session-token", "remember_token": "remember-token"}


def pane(book_id, title, author):
    return f"""
    <div class="book-pane" data-book-id="{book_id}">
      <a href="/books/{book_id}">{title}</a>
      <a href="/authors/1">{author}</a>
    </div>
    """


def response(body, status=200, headers=None):
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body.encode()))


def shelf_page(*books, up_next=(), suggestions=(), next_href=None):
    suggested = "".join(pane(*book) for book in suggestions)
    upcoming = "".join(pane(*book) for book in up_next)
    listed = "".join(pane(*book) for book in books)
    link = f'<a id="next_link" href="{next_href}">More...</a>' if next_href else ""
    return f"""
    <html><head><title>To-read | The StoryGraph</title></head><body>
      <h2>Up Next Suggestions</h2>
      {suggested}
      <h2>Up Next</h2>
      {upcoming}
      <h2>To-read</h2>
      {listed}
      {link}
    </body></html>
    """


def test_up_next_suggestions_stay_off_the_shelf_and_the_queue():
    suggestion = "22222222-2222-4222-8222-222222222222"
    html = shelf_page(
        (HARBOR, "Harbor", "Ada"),
        up_next=((QUEUE, "Queue", "Grace"),),
        suggestions=((suggestion, "Suggested", "Plus"),),
    )
    assert parse_records(html) == [{"external_id": HARBOR, "title": "Harbor", "authors": ["Ada"]}]
    assert parse_records(html, only="up-next") == [
        {"external_id": QUEUE, "title": "Queue", "authors": ["Grace"]}
    ]


def test_recovery_digest_ignores_a_rotated_storygraph_session():
    from app.domain.recovery_scans import digest
    from app.security import encrypt_secrets

    base = {"username": "nadia", "remember_token": "remember-token", "shelves": []}
    first = {
        "storygraph_accounts": [
            {
                "user_id": "u",
                "encrypted_config": encrypt_secrets({**base, "session_cookie": "session-token"}),
            }
        ]
    }
    rotated = {
        "storygraph_accounts": [
            {
                "user_id": "u",
                "encrypted_config": encrypt_secrets({**base, "session_cookie": "rotated-token"}),
            }
        ]
    }
    renamed = {
        "storygraph_accounts": [
            {
                "user_id": "u",
                "encrypted_config": encrypt_secrets(
                    {**base, "username": "ada", "session_cookie": "session-token"}
                ),
            }
        ]
    }
    assert digest(first) == digest(rotated)
    assert digest(first) != digest(renamed)
    assert digest({"users": [{"id": "u"}]}) == digest({"users": [{"id": "u"}]})


def test_username_prefers_the_account_menu_over_an_earlier_profile():
    html = """
    <html><title>Journal | The StoryGraph</title>
      <a href="/profile/friend">Friend</a>
      <header><a href="/to-read/nadia">Library</a></header>
    </html>
    """
    assert username_from(html) == "nadia"


def test_several_account_names_are_not_used():
    html = """
    <html><title>Journal | The StoryGraph</title>
      <a href="/profile/friend">Friend</a>
      <a href="/to-read/nadia">Library</a>
    </html>
    """
    crowded = """
    <header>
      <a href="/profile/nadia">Me</a>
      <a href="/profile/friend">Friend</a>
    </header>
    """
    split = """
    <header><a href="/profile/friend">Friend</a></header>
    <nav><a href="/profile/nadia">Me</a></nav>
    """
    assert username_from(html) is None
    assert username_from(crowded) is None
    assert username_from(split) is None


def test_heading_title_author_text_and_fragment_identify_the_book():
    series = "33333333-3333-4333-8333-333333333333"
    html = f"""
    <html><title>To-read | The StoryGraph</title>
      <div class="book-pane">
        <div class="book-title-author-and-series">
          <p><a href="/books/{series}">The Series</a></p>
          <h3><a href="/books/{HARBOR}#reviews">Harbor</a></h3>
          <p>Ada Lovelace</p>
          <p>Hardcover, 320 pages</p>
        </div>
      </div>
    </html>
    """
    assert parse_records(html) == [
        {"external_id": HARBOR, "title": "Harbor", "authors": ["Ada Lovelace"]}
    ]


def test_author_links_outside_the_title_block_are_ignored():
    html = f"""
    <html><title>To-read | The StoryGraph</title>
      <div class="book-pane" data-book-id="{HARBOR}">
        <div class="book-title-author-and-series">
          <h3><a href="/books/{HARBOR}">Harbor</a></h3>
          <a href="/authors/1">Ada Lovelace</a>
        </div>
        <a href="/authors/2">Someone Else</a>
      </div>
    </html>
    """
    assert parse_records(html) == [
        {"external_id": HARBOR, "title": "Harbor", "authors": ["Ada Lovelace"]}
    ]


def test_parse_shelf_separates_up_next_and_ignores_duplicate_ids():
    html = shelf_page((HARBOR, "Harbor", "Ada Lovelace"), up_next=((QUEUE, "Queue", "Grace"),))
    html += pane(HARBOR, "Harbor", "Ada Lovelace")
    assert parse_records(html) == [
        {"external_id": HARBOR, "title": "Harbor", "authors": ["Ada Lovelace"]}
    ]
    assert parse_records(html, only="up-next") == [
        {"external_id": QUEUE, "title": "Queue", "authors": ["Grace"]}
    ]


def test_parse_tag_page_keeps_title_author_and_heading():
    html = f"""
    <html><h1>Summer reading | The StoryGraph</h1>
      {pane(HARBOR, "Harbor", "Ada Lovelace")}
    </html>
    """
    assert parse_records(html) == [
        {"external_id": HARBOR, "title": "Harbor", "authors": ["Ada Lovelace"]}
    ]
    assert page_title(html, "StoryGraph list") == "Summer reading"
    branded = """
    <html><title>Summer reading | The StoryGraph</title><h1>The StoryGraph</h1></html>
    """
    assert page_title(branded, "StoryGraph list") == "Summer reading"


def test_parse_tags_dedupes_public_tag_links():
    html = f"""
    <html><title>Tags | The StoryGraph</title>
      <a href="/tags/{TAG}">Summer reading</a>
      <a href="https://app.thestorygraph.com/tags/{TAG}">Summer reading</a>
      <a href="/tags/not-a-uuid">Skip</a>
    </html>
    """
    assert parse_tags(html) == [
        {"external_id": TAG, "name": "Summer reading", "count": None, "kind": "tag"}
    ]


def test_list_url_accepts_shelves_and_tags_only():
    pasted = list_url("https://app.thestorygraph.com/To-Read/Nadia?page=2")
    assert pasted.id == "to-read"
    assert pasted.username == "Nadia"
    assert list_url("https://app.thestorygraph.com/to-read/nadia?page=2").id == "to-read"
    assert list_url("https://www.thestorygraph.com/to-read/nadia").username == "nadia"
    assert list_url(f"https://thestorygraph.com/tags/{TAG}").kind == "tag"
    assert list_url(f"https://app.thestorygraph.com/tags/{TAG}").kind == "tag"
    with pytest.raises(ValueError):
        list_url("https://app.thestorygraph.com/browse")
    with pytest.raises(ValueError):
        list_url("https://example.com/to-read/nadia")
    with pytest.raises(ValueError):
        cookies("session-token", "bad token")


async def resolver(_host):
    return ["93.184.216.34"]


def client(pages):
    def handler(request):
        page = pages[request.url.path]
        return page(request) if callable(page) else page

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_sign_in_challenge_and_empty_body_hold():
    wall = """
    <html><title>Sign in | The StoryGraph</title>
      <form action="/users/sign_in" method="post"></form>
    </html>
    """
    pages = {
        "/journal": httpx.Response(
            302, headers={"Location": "https://app.thestorygraph.com/users/sign_in"}
        ),
        "/blocked": response("Just a moment...", status=403, headers={"cf-mitigated": "challenge"}),
        "/empty": response("   "),
        "/wall": response(wall),
    }
    transport = client(pages)

    async def load(path):
        from app.adapters.storygraph import get_html

        return await get_html(SECRET, path, transport=transport, resolver=resolver)

    with pytest.raises(AdapterError) as sign_in:
        await load("/journal")
    assert sign_in.value.kind == FailureKind.AUTHENTICATION

    with pytest.raises(AdapterError) as blocked:
        await load("/blocked")
    assert blocked.value.kind == FailureKind.AUTHENTICATION
    assert "blocked" in str(blocked.value).lower()

    with pytest.raises(AdapterError) as empty:
        await load("/empty")
    assert empty.value.kind == FailureKind.PARSER

    with pytest.raises(AdapterError) as form:
        await load("/wall")
    assert form.value.kind == FailureKind.AUTHENTICATION
    assert "sign-in" in str(form.value).lower()


@pytest.mark.asyncio
async def test_pagination_stops_on_a_short_page_and_rotates_the_session():
    calls = []

    def handler(request):
        calls.append(request.headers["cookie"])
        books = [
            (f"aaaaaaaa-aaaa-4aaa-8aaa-{index:012d}", f"Book {index}", "Ada") for index in range(10)
        ]
        if len(calls) == 1:
            return response(
                shelf_page(*books, next_href="?page=2"),
                headers={"set-cookie": "_storygraph_session=rotated-token"},
            )
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert "session-token" in calls[0]
    assert "rotated-token" in calls[1]
    assert page.partial is False
    assert page.session_cookie == "rotated-token"
    assert page.items[-1]["title"] == "Harbor"
    assert len(page.items) == 11


@pytest.mark.asyncio
async def test_page_cap_marks_the_observation_partial():
    seen = []

    def handler(request):
        query = dict(parse_qsl(request.url.query.decode()))
        page_number = int(query.get("page", "1"))
        seen.append(page_number)
        start = (page_number - 1) * 10
        books = [
            (f"{start + index:08x}-bbbb-4bbb-8bbb-bbbbbbbbbbbb", f"Book {start + index}", "Ada")
            for index in range(10)
        ]
        return response(shelf_page(*books, next_href=f"?page={page_number + 1}"))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/books-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert seen == list(range(1, 21))
    assert page.partial is True
    assert len(page.items) == 200


def _ten_books():
    return [
        (f"aaaaaaaa-aaaa-4aaa-8aaa-{index:012d}", f"Book {index}", "Ada") for index in range(10)
    ]


@pytest.mark.asyncio
async def test_a_blank_page_does_not_end_the_list():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        if len(calls) == 1:
            return response(
                "<html><title>To-read | The StoryGraph</title>"
                '<a id="next_link" href="?page=2">More</a></html>'
            )
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [b"", b"page=2"]
    assert page.partial is False
    assert page.items == [{"external_id": HARBOR, "title": "Harbor", "authors": ["Ada"]}]


@pytest.mark.asyncio
async def test_a_usable_next_link_follows_an_unusable_one():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        if len(calls) == 1:
            return response(
                shelf_page(*_ten_books())
                + '<a id="next_link" href="javascript:alert(1)">More</a>'
                + '<a rel="next" href="?page=2">Next</a>'
            )
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [b"", b"page=2"]
    assert page.items[-1]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_the_next_public_address_is_used_when_the_first_refuses():
    def handler(request):
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("refused")
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    async def alternate(_host):
        return ["93.184.216.34", "93.184.216.35"]

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=alternate,
        pause=0,
    )
    assert page.items[0]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_a_skipped_page_number_stays_partial():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        return response(shelf_page(*_ten_books(), next_href="?page=4"))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [b""]
    assert page.partial is True
    assert len(page.items) == 10


@pytest.mark.asyncio
async def test_a_book_titled_just_a_moment_is_still_a_book():
    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(
            lambda _request: response(shelf_page((HARBOR, "Just a Moment", "Ada")))
        ),
        resolver=resolver,
        pause=0,
    )
    assert page.items == [{"external_id": HARBOR, "title": "Just a Moment", "authors": ["Ada"]}]


@pytest.mark.asyncio
async def test_sign_in_redirect_does_not_replace_the_session():
    from app.adapters.storygraph import get_html

    def handler(_request):
        return httpx.Response(
            302,
            headers={
                "Location": "https://app.thestorygraph.com/users/sign_in",
                "set-cookie": "_storygraph_session=logged-out-token",
            },
        )

    holder = {}
    with pytest.raises(AdapterError) as error:
        await get_html(
            SECRET,
            "/journal",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.AUTHENTICATION
    assert holder == {}


@pytest.mark.asyncio
async def test_sign_in_page_does_not_replace_the_session():
    from app.adapters.storygraph import get_html

    body = "<html><body><form action='/users/sign_in'></form></body></html>"
    holder = {}
    with pytest.raises(AdapterError) as error:
        await get_html(
            SECRET,
            "/journal",
            transport=httpx.MockTransport(
                lambda _request: response(
                    body, headers={"set-cookie": "_storygraph_session=logged-out-token"}
                )
            ),
            resolver=resolver,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.AUTHENTICATION
    assert holder == {}


def test_retarget_keeps_friend_shelves_and_follows_a_renamed_account():
    owned = {"kind": "shelf", "id": "to-read", "username": "nadia"}
    friend = {"kind": "shelf", "id": "to-read", "username": "grace"}
    assert retarget_config(owned, "nadia", "nadia-new")["username"] == "nadia-new"
    assert retarget_config(friend, "nadia", "nadia-new")["username"] == "grace"
    assert retarget_config(owned, "nadia", "nadia") is owned


@pytest.mark.asyncio
async def test_a_full_page_without_a_next_link_is_complete():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        return response(shelf_page(*_ten_books()))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [b""]
    assert page.partial is False
    assert len(page.items) == 10


@pytest.mark.asyncio
async def test_next_link_must_stay_on_this_list():
    for href in (
        "https://evil.example/to-read/nadia?page=2",
        "/books-read/nadia?page=2",
        "javascript:alert(1)",
    ):
        calls = []

        def handler(request, href=href, calls=calls):
            calls.append(request.url.path)
            return response(shelf_page(*_ten_books(), next_href=href))

        page = await read_list(
            SECRET,
            list_url("https://app.thestorygraph.com/to-read/nadia"),
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            pause=0,
        )
        assert calls == ["/to-read/nadia"]
        assert page.partial is True
        assert len(page.items) == 10


@pytest.mark.asyncio
async def test_rel_next_is_followed_when_it_stays_on_this_list():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        if len(calls) == 1:
            body = shelf_page(*_ten_books()).replace(
                "</body>", '<a rel="next" href="?page=2">Next</a></body>'
            )
            return response(body)
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert len(calls) == 2
    assert page.items[-1]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_a_repeated_next_page_stays_partial():
    def handler(request):
        query = dict(parse_qsl(request.url.query.decode()))
        page_number = int(query.get("page", "1"))
        return response(shelf_page(*_ten_books(), next_href=f"?page={page_number + 1}"))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert page.partial is True
    assert len(page.items) == 10


@pytest.mark.asyncio
async def test_a_failed_later_page_keeps_the_rotated_session():
    def handler(request):
        if request.url.query:
            return response(
                "Just a moment...",
                status=403,
                headers={
                    "cf-mitigated": "challenge",
                    "set-cookie": "_storygraph_session=blocked-token",
                },
            )
        return response(
            shelf_page(*_ten_books(), next_href="?page=2"),
            headers={"set-cookie": "_storygraph_session=rotated-token"},
        )

    holder = {}
    with pytest.raises(AdapterError) as error:
        await read_list(
            SECRET,
            list_url("https://app.thestorygraph.com/to-read/nadia"),
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            pause=0,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.AUTHENTICATION
    assert holder["session_cookie"] == "rotated-token"


@pytest.mark.asyncio
async def test_up_next_is_a_single_page():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return response(
            shelf_page(
                (HARBOR, "Harbor", "Ada"),
                up_next=((QUEUE, "Queue", "Grace"),),
                next_href="?page=2",
            )
        )

    page = await read_list(
        SECRET,
        Target("shelf", "up-next", "nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == ["/to-read/nadia"]
    assert page.name == "Up Next"
    assert page.items == [{"external_id": QUEUE, "title": "Queue", "authors": ["Grace"]}]
    assert page.partial is False


@pytest.mark.asyncio
async def test_discover_reads_profile_up_next_and_tags():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/journal":
            return response(
                "<html><title>Journal | The StoryGraph</title>"
                '<a href="/profile/nadia">Nadia</a></html>'
            )
        if request.url.path.startswith("/to-read/"):
            return response(
                shelf_page((HARBOR, "Harbor", "Ada"), up_next=((QUEUE, "Queue", "Grace"),))
            )
        return response(
            f'<html><title>Tags | The StoryGraph</title><a href="/tags/{TAG}">Summer</a></html>'
        )

    account = await discover(
        SECRET, transport=httpx.MockTransport(handler), resolver=resolver, pause=0
    )
    assert seen == ["/journal", "/to-read/nadia", "/your-tags"]
    assert account["username"] == "nadia"
    ids = [shelf["external_id"] for shelf in account["shelves"]]
    assert ids[:4] == ["to-read", "currently-reading", "books-read", "favorites"]
    assert "up-next" in ids
    assert TAG in ids


def test_a_book_heading_named_up_next_does_not_hide_the_shelf():
    html = f"""
    <html><body>
      <h3>Up Next</h3>
      {pane(QUEUE, "Up Next", "Ada")}
      {pane(HARBOR, "Harbor", "Grace")}
    </body></html>
    """
    assert [item["external_id"] for item in parse_records(html)] == [QUEUE, HARBOR]
    assert parse_records(html, only="up-next") == []


def test_a_broken_saved_login_asks_for_a_reconnect():
    from app.adapters.storygraph import open_session, stored_target

    with pytest.raises(AdapterError) as login:
        open_session({})
    assert login.value.kind == FailureKind.AUTHENTICATION
    with pytest.raises(AdapterError) as listed:
        stored_target({})
    assert listed.value.kind == FailureKind.PARSER


@pytest.mark.asyncio
async def test_a_next_link_keeps_its_filters():
    calls = []

    def handler(request):
        calls.append(request.url.query)
        if len(calls) == 1:
            return response(shelf_page(*_ten_books(), next_href="?page=2&sort=title"))
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [b"", b"page=2&sort=title"]
    assert page.partial is False
    assert page.items[-1]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_a_redirect_away_from_the_page_does_not_replace_the_session():
    from app.adapters.storygraph import get_html

    def handler(_request):
        return httpx.Response(
            302,
            headers={
                "Location": "https://app.thestorygraph.com/",
                "set-cookie": "_storygraph_session=logged-out-token",
            },
        )

    holder = {}
    with pytest.raises(AdapterError) as error:
        await get_html(
            SECRET,
            "/journal",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.UNAVAILABLE
    assert holder == {}


@pytest.mark.asyncio
async def test_a_redirect_on_the_same_page_keeps_the_rotated_session():
    from app.adapters.storygraph import get_html

    def handler(_request):
        return httpx.Response(
            302,
            headers={
                "Location": "https://app.thestorygraph.com/journal",
                "set-cookie": "_storygraph_session=rotated-token",
            },
        )

    holder = {}
    with pytest.raises(AdapterError) as error:
        await get_html(
            SECRET,
            "/journal",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.UNAVAILABLE
    assert holder == {"session_cookie": "rotated-token"}


def test_a_book_nested_inside_another_card_is_not_a_separate_entry():
    nested = "33333333-3333-4333-8333-333333333333"
    html = f"""
    <html><body>
      <div class="book-pane" data-book-id="{HARBOR}">
        <div class="book-title-author-and-series">
          <h3><a href="/books/{HARBOR}">Harbor</a></h3>
          <a href="/authors/1">Ada</a>
        </div>
        <div class="book-pane" data-book-id="{nested}">
          <div class="book-title-author-and-series">
            <h3><a href="/books/{nested}">Nested</a></h3>
            <a href="/authors/2">Grace</a>
          </div>
        </div>
      </div>
    </body></html>
    """
    assert parse_records(html) == [{"external_id": HARBOR, "title": "Harbor", "authors": ["Ada"]}]


def test_a_longer_up_next_heading_does_not_hide_the_shelf():
    html = f"""
    <html><body>
      <h2>Up Next in the Series</h2>
      {pane(HARBOR, "Harbor", "Ada")}
      <h2>Up Next 3</h2>
      {pane(QUEUE, "Queue", "Grace")}
    </body></html>
    """
    assert [item["title"] for item in parse_records(html)] == ["Harbor"]
    assert [item["title"] for item in parse_records(html, only="up-next")] == ["Queue"]


def test_a_tag_link_inside_a_book_card_is_not_one_of_your_tags():
    other = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    html = f"""
    <html><body>
      <div class="book-pane"><a href="/tags/{TAG}">From a book</a></div>
      <a href="/tags/{other}">Mine</a>
    </body></html>
    """
    assert parse_tags(html) == [
        {"external_id": other, "name": "Mine", "count": None, "kind": "tag"}
    ]


def test_a_public_host_book_link_is_still_the_book():
    html = f"""
    <html><body>
      <div class="book-pane">
        <a href="https://www.thestorygraph.com/books/{HARBOR}#reviews">Harbor</a>
        <a href="//thestorygraph.com/authors/1">Ada</a>
      </div>
    </body></html>
    """
    assert parse_records(html) == [{"external_id": HARBOR, "title": "Harbor", "authors": ["Ada"]}]
    other = f'<div class="book-pane"><a href="https://evil.example/books/{HARBOR}">Harbor</a></div>'
    assert parse_records(other) == []


@pytest.mark.asyncio
async def test_a_next_link_on_the_public_host_stays_on_this_list():
    calls = []
    href = "https://www.thestorygraph.com/to-read/nadia?page=2"

    def handler(request):
        calls.append((request.url.path, request.url.query))
        if len(calls) == 1:
            return response(shelf_page(*_ten_books(), next_href=href))
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [("/to-read/nadia", b""), ("/to-read/nadia", b"page=2")]
    assert page.partial is False
    assert page.items[-1]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_a_same_list_redirect_on_the_public_host_keeps_the_session():
    from app.adapters.storygraph import get_html

    def handler(_request):
        return httpx.Response(
            302,
            headers={
                "Location": "https://www.thestorygraph.com/journal",
                "set-cookie": "_storygraph_session=rotated-token",
            },
        )

    holder = {}
    with pytest.raises(AdapterError) as error:
        await get_html(
            SECRET,
            "/journal",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            session_out=holder,
        )
    assert error.value.kind == FailureKind.UNAVAILABLE
    assert holder == {"session_cookie": "rotated-token"}


def test_an_incomplete_saved_list_has_no_identity():
    from app.adapters.storygraph import identity

    assert identity({}) is None
    owned = {"kind": "shelf", "id": "to-read", "username": "nadia"}
    assert identity(owned) == "shelf:nadia:to-read"


@pytest.mark.asyncio
async def test_a_next_link_keeps_an_encoded_filter():
    calls = []

    def handler(request):
        calls.append(dict(parse_qsl(request.url.query.decode())))
        if len(calls) == 1:
            return response(shelf_page(*_ten_books(), next_href="?page=2&sort=title+asc"))
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == [{}, {"page": "2", "sort": "title asc"}]
    assert page.partial is False
    assert page.items[-1]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_a_saved_shelf_with_a_bad_username_is_not_requested():
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return response(shelf_page((HARBOR, "Harbor", "Ada")))

    with pytest.raises(AdapterError) as error:
        await read_list(
            SECRET,
            Target("shelf", "to-read", "nadia/../journal"),
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            pause=0,
        )
    assert error.value.kind == FailureKind.PARSER
    assert called is False


def test_a_wrapped_section_does_not_swallow_the_rest_of_the_shelf():
    html = f"""
    <html><body>
      <h2>Up Next</h2>
      <div>
        {pane(QUEUE, "Queue", "Grace")}
        <h2>To-read</h2>
        {pane(HARBOR, "Harbor", "Ada")}
      </div>
    </body></html>
    """
    assert [item["title"] for item in parse_records(html, only="up-next")] == ["Queue"]
    assert [item["title"] for item in parse_records(html)] == ["Harbor"]


def test_the_heading_link_is_the_title_when_the_heading_also_names_the_series():
    html = f"""
    <html><body>
      <div class="book-pane" data-book-id="{HARBOR}">
        <div class="book-title-author-and-series">
          <h3><a href="/books/{HARBOR}">Harbor</a> The Series</h3>
          <p>Hardcover, 320 pages</p>
          <p>Ada Lovelace</p>
        </div>
      </div>
    </body></html>
    """
    assert parse_records(html) == [
        {"external_id": HARBOR, "title": "Harbor", "authors": ["Ada Lovelace"]}
    ]


@pytest.mark.asyncio
async def test_a_next_link_inside_a_book_card_does_not_end_the_list():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        extra = f'<div class="book-pane"><a rel="next" href="/books/{QUEUE}">Next</a></div>'
        body = shelf_page((HARBOR, "Harbor", "Ada")).replace("</body>", extra + "</body>")
        return response(body)

    page = await read_list(
        SECRET,
        list_url("https://app.thestorygraph.com/to-read/nadia"),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        pause=0,
    )
    assert calls == ["/to-read/nadia"]
    assert page.partial is False
    assert page.items[0]["title"] == "Harbor"


@pytest.mark.asyncio
async def test_an_unnamed_account_page_asks_for_a_reconnect():
    def handler(_request):
        return response("<html><title>Journal | The StoryGraph</title></html>")

    with pytest.raises(AdapterError) as error:
        await discover(
            SECRET,
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            pause=0,
        )
    assert error.value.kind == FailureKind.AUTHENTICATION
