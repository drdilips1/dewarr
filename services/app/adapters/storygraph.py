"""Signed-in StoryGraph shelf and tag pages. Observations never imply removals."""

import asyncio
import contextvars
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.adapters.contracts import AdapterError, FailureKind
from app.importing.covers import CoverError, public_address, public_addresses

ORIGIN = "https://app.thestorygraph.com"
HOST = "app.thestorygraph.com"
PASTE_HOSTS = {HOST, "www.thestorygraph.com", "thestorygraph.com"}
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SHELVES = {
    "to-read": "To-read",
    "currently-reading": "Currently reading",
    "books-read": "Read",
    "favorites": "Favorites",
    "up-next": "Up Next",
}
USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# RFC 6265 cookie-octet: no spaces, quotes, commas, semicolons, or backslashes.
TOKEN_RE = re.compile(r"^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]{8,4096}$")
COOKIE_NAMES = ("_storygraph_session", "remember_user_token")
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff\xa0]")
HELD = "StoryGraph did not return this list; existing books are preserved"
SIGN_IN = "StoryGraph asked for a sign-in. Reconnect the account; existing books are preserved"
BLOCKED = "StoryGraph blocked this check. Existing books are preserved"
_request = contextvars.ContextVar("storygraph_request", default=False)


class SessionLogFilter(logging.Filter):
    def filter(self, record):
        return not _request.get()


logging.getLogger("httpx").addFilter(SessionLogFilter())
logging.getLogger("httpcore").addFilter(SessionLogFilter())


@dataclass(frozen=True)
class Target:
    kind: str
    id: str
    username: str | None


@dataclass
class Page:
    html: str
    session_cookie: str | None


@dataclass
class ListResult:
    items: list[dict]
    partial: bool
    session_cookie: str | None
    name: str


def _clean_cookie(value):
    """Keep a copied cookie value. Browser panes wrap it, quote it, or encode '='."""
    value = _INVISIBLE.sub("", value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    value = re.sub(r"\s+", "", value)
    if "%" in value:
        decoded = re.sub(r"\s+", "", unquote(value))
        if TOKEN_RE.fullmatch(decoded):
            return decoded
    return value


def _pasted_cookies(text):
    """Pull named cookies out of a header, a name=value pair, or a devtools row."""
    if not isinstance(text, str) or not text.strip():
        return {}
    found = {}
    labeled = re.sub(r"(?i)^cookie:\s*", "", text.strip())
    for chunk in re.split(r"[;\r\n]+", labeled):
        chunk = chunk.strip()
        if "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        name = _INVISIBLE.sub("", name).strip()
        if name in COOKIE_NAMES:
            found[name] = _clean_cookie(value)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0] in COOKIE_NAMES and lines[0] not in found:
        found[lines[0]] = _clean_cookie(lines[1])
    columns = re.split(r"[\t ]+", text.strip())
    if len(columns) >= 2 and columns[0] in COOKIE_NAMES and columns[0] not in found:
        found[columns[0]] = _clean_cookie(columns[1])
    return found


def cookies(session_cookie, remember_token):
    found = {}
    for raw in (session_cookie, remember_token):
        for name, value in _pasted_cookies(raw).items():
            found.setdefault(name, value)
    session_cookie = found.get("_storygraph_session") or _clean_cookie(session_cookie)
    remember_token = found.get("remember_user_token") or _clean_cookie(remember_token)
    if TOKEN_RE.fullmatch(session_cookie) and TOKEN_RE.fullmatch(remember_token):
        return {"session_cookie": session_cookie, "remember_token": remember_token}
    bad = [
        name
        for name, value in (
            ("_storygraph_session", session_cookie),
            ("remember_user_token", remember_token),
        )
        if not TOKEN_RE.fullmatch(value)
    ]
    raise ValueError(
        "Copy only the Value of "
        + " and ".join(bad)
        + ". Leave out the cookie name, quotes, and any other columns."
    )


def session(config):
    return cookies(config["session_cookie"], config["remember_token"])


def open_session(config):
    """Load a stored login. A broken secret asks for a reconnect instead of crashing."""
    try:
        return session(config)
    except (KeyError, TypeError, ValueError):
        raise AdapterError(FailureKind.AUTHENTICATION, SIGN_IN) from None


def identity(config):
    try:
        if config["kind"] == "tag":
            return f"tag:{config['id']}"
        return f"shelf:{config['username']}:{config['id']}"
    except (KeyError, TypeError):
        return None


def retarget_config(config, seen_username, username):
    """Point an owned list at a username that changed while its follow was in flight."""
    if (
        not seen_username
        or not username
        or seen_username == username
        or config.get("username") != seen_username
    ):
        return config
    return {**config, "username": username}


def target_from_config(config):
    username = config.get("username")
    if config["kind"] == "shelf" and not username:
        raise AdapterError(FailureKind.PARSER, HELD)
    return Target(config["kind"], config["id"], username)


def stored_target(config):
    try:
        return target_from_config(config)
    except (KeyError, TypeError):
        raise AdapterError(FailureKind.PARSER, HELD) from None


def is_storygraph_host(hostname):
    return hostname in PASTE_HOSTS


def list_url(value):
    try:
        parts = urlsplit(value.strip())
        query = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=5)
        path = parts.path.rstrip("/") or "/"
        if (
            parts.scheme != "https"
            or not is_storygraph_host(parts.hostname)
            or parts.port not in {None, 443}
            or parts.username
            or parts.password
            or parts.fragment
            or "\\" in value
            or len(value) > 2000
            or any(ord(c) < 33 for c in value)
            or any(key != "page" or not item.isdigit() for key, item in query)
        ):
            raise ValueError
        shelf = re.fullmatch(
            r"/(to-read|currently-reading|books-read|favorites)/([A-Za-z0-9][A-Za-z0-9_-]{0,39})",
            path,
            re.I,
        )
        if shelf and USER_RE.fullmatch(shelf[2]):
            return Target("shelf", shelf[1].lower(), shelf[2])
        tag = re.fullmatch(r"/tags/([0-9a-fA-F-]{36})", path)
        if tag and UUID_RE.fullmatch(tag[1].lower()):
            return Target("tag", tag[1].lower(), None)
    except (ValueError, TypeError):
        pass
    raise ValueError(
        "Use a StoryGraph to-read, currently reading, read, favorites, or public tag link"
    )


def _clean(value, limit):
    text = " ".join((value or "").split())
    return text[:limit]


def _href_path(href):
    if not href or href.startswith(("javascript:", "data:", "mailto:")):
        return ""
    parts = urlsplit(urljoin(ORIGIN, href))
    if parts.hostname not in PASTE_HOSTS:
        return ""
    return parts.path


def _book_id(path):
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "books" and UUID_RE.fullmatch(parts[1].lower()):
        return parts[1].lower()
    return ""


def _inside_other_pane(node, root):
    parent = node.find_parent(class_="book-pane")
    return parent is not None and parent is not root


def _record(pane):
    block = next(
        (
            item
            for item in pane.select(".book-title-author-and-series")
            if not _inside_other_pane(item, pane)
        ),
        None,
    )
    book_id = (pane.get("data-book-id") or "").lower()
    links = []
    if block:
        links.extend(
            link
            for link in block.select("a[href*='/books/']")
            if not _inside_other_pane(link, pane)
        )
    links.extend(
        link for link in pane.select("a[href*='/books/']") if not _inside_other_pane(link, pane)
    )
    if not UUID_RE.fullmatch(book_id):
        heading_link = block.select_one("h3 a[href*='/books/']") if block else None
        if heading_link is not None and _inside_other_pane(heading_link, pane):
            heading_link = None
        link = heading_link or next(iter(links), None)
        book_id = _book_id(_href_path(link.get("href") if link else ""))
    if not UUID_RE.fullmatch(book_id):
        return None
    title = ""
    if block:
        heading = block.select_one("h3")
        if heading is not None and not _inside_other_pane(heading, pane):
            link = heading.select_one("a[href*='/books/']")
            if link is not None and book_id in _href_path(link.get("href", "")).lower():
                title = _clean(link.get_text(" ", strip=True), 600)
            if not title:
                title = _clean(heading.get_text(" ", strip=True), 600)
    if not title:
        for link in links:
            if book_id in _href_path(link.get("href", "")).lower():
                title = _clean(link.get_text(" ", strip=True), 600)
                if title:
                    break
    authors = []
    author_scope = block if block is not None else pane
    for link in author_scope.select("a[href*='/authors/']"):
        if _inside_other_pane(link, pane):
            continue
        name = _clean(link.get_text(" ", strip=True), 300)
        if name and name not in authors:
            authors.append(name)
    if not authors and block:
        for paragraph in block.find_all("p"):
            if _inside_other_pane(paragraph, pane) or paragraph.select_one("a[href*='/books/']"):
                continue
            name = _clean(paragraph.get_text(" ", strip=True), 300)
            if re.search(r"\b(pages|hardcover|paperback|audiobook|ebook|kindle)\b", name, re.I):
                continue
            if name:
                authors.append(name)
                break
    if not title:
        return None
    return {"external_id": book_id, "title": title, "authors": authors}


def _heading_kind(text):
    words = " ".join(text.lower().split())
    if "up next" in words and "suggest" in words:
        return "suggestions"
    # "Up Next Suggestions" is a Plus shelf and must not match the reader's queue.
    # A longer heading such as "Up Next in the Series" is a book title, not the queue.
    if re.fullmatch(r"up next(?:\s+\d+|\s*\([^)]*\))?", words):
        return "queue"
    return None


def _panes_after(heading):
    """Books after this heading and before the next section heading.

    The next heading may sit inside a wrapper with these books, so sibling order
    alone would treat the rest of the page as this section.
    """
    panes = []
    for element in heading.next_elements:
        name = getattr(element, "name", None)
        if name in {"h1", "h2"} and element.find_parent(class_="book-pane") is None:
            break
        if name is None or "book-pane" not in (element.get("class") or []):
            continue
        if element.find_parent(class_="book-pane") is None:
            panes.append(element)
    return panes


def _section_panes(soup, kind):
    panes = []
    for tag in soup.find_all(["h1", "h2", "summary"]):
        if tag.find_parent(class_="book-pane"):
            continue
        if _heading_kind(tag.get_text(" ", strip=True)) == kind:
            panes.extend(_panes_after(tag))
    return panes


def parse_records(html, *, only=None):
    soup = BeautifulSoup(html or "", "html.parser")
    suggestions = {id(pane) for pane in _section_panes(soup, "suggestions")}
    queued = [pane for pane in _section_panes(soup, "queue") if id(pane) not in suggestions]
    if only == "up-next":
        chosen = queued
    else:
        skip = suggestions | {id(pane) for pane in queued}
        chosen = [
            pane
            for pane in soup.select(".book-pane")
            if id(pane) not in skip and pane.find_parent(class_="book-pane") is None
        ]
    records = {}
    for pane in chosen:
        record = _record(pane)
        if record and record["external_id"] not in records:
            records[record["external_id"]] = record
    return list(records.values())


def parse_tags(html):
    soup = BeautifulSoup(html or "", "html.parser")
    tags, seen = [], set()
    for link in soup.select("a[href*='/tags/']"):
        if link.find_parent(class_="book-pane"):
            continue
        parts = _href_path(link.get("href")).strip("/").split("/")
        if len(parts) != 2 or parts[0] != "tags" or not UUID_RE.fullmatch(parts[1].lower()):
            continue
        tag_id = parts[1].lower()
        name = _clean(link.get_text(" ", strip=True), 200)
        if not name or tag_id in seen:
            continue
        seen.add(tag_id)
        tags.append({"external_id": tag_id, "name": name, "count": None, "kind": "tag"})
    return tags


def _named(raw):
    title = re.sub(
        r"\s*[|–—-]\s*the storygraph$",
        "",
        _clean(raw, 200),
        flags=re.I,
    ).strip()
    if title and title.lower() not in {"the storygraph", "storygraph"}:
        return title
    return ""


def page_title(html, fallback):
    soup = BeautifulSoup(html or "", "html.parser")
    for node in (soup.find("title"), soup.find("h1")):
        if node is None:
            continue
        title = _named(node.get_text(" ", strip=True))
        if title:
            return title
    return fallback


def _usernames_in(scope):
    found = []
    for link in scope.select("a[href]"):
        if link.find_parent(class_="book-pane"):
            continue
        parts = _href_path(link.get("href")).strip("/").split("/")
        if (
            len(parts) == 2
            and parts[0] in {"profile", "to-read", "currently-reading", "books-read", "favorites"}
            and USER_RE.fullmatch(parts[1])
            and parts[1] not in found
        ):
            found.append(parts[1])
    return found


def username_from(html):
    """The signed-in reader, or None when the page does not name exactly one."""
    soup = BeautifulSoup(html or "", "html.parser")
    chrome = []
    for scope in soup.select("header, nav"):
        for name in _usernames_in(scope):
            if name not in chrome:
                chrome.append(name)
    if len(chrome) == 1:
        return chrome[0]
    if chrome:
        return None
    found = _usernames_in(soup)
    return found[0] if len(found) == 1 else None


def _challenge(html):
    lowered = (html or "").lower()
    if "cf-browser-verification" in lowered:
        return True
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.find("title")
    text = title.get_text(" ", strip=True).lower() if title else ""
    return "just a moment" in text


def _login_wall(html):
    soup = BeautifulSoup(html or "", "html.parser")
    wall = soup.select_one("form[action*='sign_in'], form[action*='sign-in']")
    return bool(wall) and not soup.select(".book-pane")


def _acceptable(html):
    if not (html or "").strip() or _challenge(html) or _login_wall(html):
        return False
    lowered = html.lower()
    return "book-pane" in lowered or "the storygraph" in lowered or "filter list" in lowered


def _ends_session(location):
    lowered = location.lower()
    return any(
        part in lowered
        for part in ("/users/sign_in", "/users/sign-in", "/users/sign_out", "/users/sign-out")
    )


def _rotated_session(headers):
    for cookie in headers.get_list("set-cookie"):
        match = re.match(r"_storygraph_session=([^;]+)", cookie)
        if match and TOKEN_RE.fullmatch(match.group(1)):
            return match.group(1)
    return None


def _retry_after(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 60
    return max(60, min(seconds, 86400))


def _href_text(link):
    href = link.get("href") or ""
    if isinstance(href, list):
        href = href[0] if href else ""
    return href


def _same_list_path(left, right):
    current, other = (left or "").rstrip("/"), (right or "").rstrip("/")
    if current == other:
        return True
    return current.lower().startswith("/tags/") and current.lower() == other.lower()


def _linked_page(href, path):
    """Return (page number, exact URL) for a More link on this same list."""
    if not href or href.startswith(("javascript:", "data:")):
        return None
    base = _resource(path, 1)
    joined = urlsplit(urljoin(base, href))
    current = urlsplit(base)
    if (
        joined.scheme != "https"
        or joined.hostname not in PASTE_HOSTS
        or joined.port not in {None, 443}
    ):
        return None
    if joined.username or joined.password or not _same_list_path(current.path, joined.path):
        return None
    if len(joined.query) > 200:
        return None
    pairs = []
    page = None
    for key, value in parse_qsl(joined.query, keep_blank_values=False):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", key):
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.,~%+ -]{1,40}", value):
            return None
        if key == "page":
            if page is not None:
                return None
            page = value
        pairs.append((key, value))
    if page is None or not page.isdigit() or not 2 <= int(page) <= 1000:
        return None
    url = urlunsplit(("https", HOST, current.path, urlencode(pairs), ""))
    return int(page), url


def _next_step(html, path):
    """Return the next request on this same list.

    None means this page is the last one. (0, None) means a More link is present but
    cannot be followed, so the observation is incomplete.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    links = []

    def pagination(link):
        return link.find_parent(class_="book-pane") is None

    primary = soup.find(id="next_link")
    if primary is not None and pagination(primary):
        links.append(primary)
    links.extend(
        link for link in soup.find_all("a", rel="next") if link not in links and pagination(link)
    )
    if not links:
        return None
    for link in links:
        found = _linked_page(_href_text(link), path)
        if found:
            return found
    return 0, None


def _stays_on_page(location, url):
    if not location:
        return False
    joined = urlsplit(urljoin(url, location))
    current = urlsplit(url)
    return (
        joined.scheme == "https"
        and joined.hostname in PASTE_HOSTS
        and joined.port in {None, 443}
        and not joined.username
        and not joined.password
        and _same_list_path(current.path, joined.path)
    )


def _resource(path, page):
    parts = urlsplit(path if path.startswith("http") else f"{ORIGIN}{path}")
    query = dict(parse_qsl(parts.query, keep_blank_values=False))
    if page > 1:
        query["page"] = str(page)
    else:
        query.pop("page", None)
    return urlunsplit(
        ("https", HOST, parts.path, "&".join(f"{k}={v}" for k, v in query.items()), "")
    )


async def get_html(
    cookies,
    path,
    *,
    page=1,
    target=None,
    transport=None,
    resolver=public_addresses,
    session_out=None,
):
    url = target or _resource(path, page)
    marker = _request.set(True)
    try:
        async with asyncio.timeout(30):
            addresses = await resolver(HOST)
            if not addresses or any(not public_address(address) for address in addresses):
                raise AdapterError(FailureKind.ROUTE, HELD)
            headers = {
                "Host": HOST,
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Cookie": (
                    f"remember_user_token={cookies['remember_token']}; "
                    f"_storygraph_session={cookies['session_cookie']}"
                ),
            }
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(15, connect=5),
                headers=headers,
            ) as client:
                response = None
                opened = None
                for address in addresses[:4]:
                    attempt = AsyncExitStack()
                    target = httpx.URL(url).copy_with(host=address)
                    try:
                        response = await attempt.enter_async_context(
                            client.stream("GET", target, extensions={"sni_hostname": HOST})
                        )
                    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.InvalidURL):
                        await attempt.aclose()
                        continue
                    opened = attempt
                    break
                if response is None or opened is None:
                    raise AdapterError(FailureKind.ROUTE, HELD)
                try:
                    status = response.status_code
                    rotated = _rotated_session(response.headers)
                    location = response.headers.get("location", "")
                    if status in {301, 302, 303, 307, 308}:
                        if _ends_session(location):
                            raise AdapterError(FailureKind.AUTHENTICATION, SIGN_IN)
                        if _stays_on_page(location, url):
                            _remember(session_out, rotated)
                        raise AdapterError(FailureKind.UNAVAILABLE, HELD)
                    if status == 429:
                        _remember(session_out, rotated)
                        raise AdapterError(
                            FailureKind.RATE_LIMIT,
                            "StoryGraph is limiting requests; observation will retry later",
                            retry_after=_retry_after(response.headers.get("retry-after")),
                        )
                    if status in {401, 403} or response.headers.get("cf-mitigated"):
                        raise AdapterError(FailureKind.AUTHENTICATION, BLOCKED)
                    if status != 200:
                        _remember(session_out, rotated)
                        raise AdapterError(FailureKind.UNAVAILABLE, HELD)
                    content = bytearray()
                    async for chunk in response.aiter_raw():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            _remember(session_out, rotated)
                            raise AdapterError(FailureKind.PARSER, HELD)
                    html = bytes(content).decode("utf-8", "replace")
                    if _challenge(html):
                        raise AdapterError(FailureKind.AUTHENTICATION, BLOCKED)
                    if _login_wall(html):
                        raise AdapterError(FailureKind.AUTHENTICATION, SIGN_IN)
                    if not _acceptable(html):
                        _remember(session_out, rotated)
                        raise AdapterError(FailureKind.PARSER, HELD)
                    _remember(session_out, rotated)
                    return Page(html, rotated)
                finally:
                    await opened.aclose()
    except AdapterError:
        raise
    except (httpx.HTTPError, TimeoutError, OSError, CoverError):
        raise AdapterError(FailureKind.ROUTE, HELD) from None
    finally:
        _request.reset(marker)


def _remember(session_out, value):
    if session_out is not None and value:
        session_out["session_cookie"] = value


async def read_list(
    cookies, target, *, transport=None, resolver=public_addresses, pause=1.5, session_out=None
):
    if target.kind == "tag":
        if not UUID_RE.fullmatch(target.id or ""):
            raise AdapterError(FailureKind.PARSER, HELD)
    elif (
        target.kind != "shelf"
        or target.id not in SHELVES
        or not USER_RE.fullmatch(target.username or "")
    ):
        raise AdapterError(FailureKind.PARSER, HELD)
    path = (
        f"/tags/{target.id}"
        if target.kind == "tag"
        else f"/{'to-read' if target.id == 'up-next' else target.id}/{target.username}"
    )
    only = "up-next" if target.id == "up-next" else None
    pages = 1 if target.id == "up-next" else MAX_PAGES
    items, seen, session, partial = [], set(), None, False
    current = dict(cookies)
    number, fetched = 1, 0
    pending = None
    while fetched < pages:
        if fetched and pause:
            await asyncio.sleep(pause)
        document = await get_html(
            current,
            path,
            page=number,
            target=pending,
            transport=transport,
            resolver=resolver,
            session_out=session_out,
        )
        fetched += 1
        if document.session_cookie:
            session = document.session_cookie
            current["session_cookie"] = session
            _remember(session_out, session)
        batch = parse_records(document.html, only=only)
        fresh = [record for record in batch if record["external_id"] not in seen]
        seen.update(record["external_id"] for record in fresh)
        items.extend(fresh)
        step = None if only else _next_step(document.html, path)
        if only or step is None:
            break
        upcoming, pending = step
        # An empty page can sit in front of the rest of the list. A page that
        # repeats books already seen is a loop, so that check stops there.
        repeated = bool(batch) and not fresh
        if repeated or upcoming != number + 1 or fetched == pages:
            partial = True
            break
        number = upcoming
    name = (
        SHELVES[target.id]
        if target.kind == "shelf"
        else page_title(document.html, "StoryGraph list")
    )
    return ListResult(items, partial, session, name)


async def discover(
    cookies, *, transport=None, resolver=public_addresses, pause=1.5, session_out=None
):
    current = dict(cookies)
    session = None

    async def load(path):
        nonlocal session
        if pause and session is not None:
            await asyncio.sleep(pause)
        document = await get_html(
            current, path, transport=transport, resolver=resolver, session_out=session_out
        )
        if document.session_cookie:
            session = document.session_cookie
            current["session_cookie"] = document.session_cookie
            _remember(session_out, session)
        elif session is None:
            session = current["session_cookie"]
        return document

    journal = await load("/journal")
    username = username_from(journal.html)
    if not username:
        raise AdapterError(FailureKind.AUTHENTICATION, SIGN_IN)
    to_read_path = f"/to-read/{username}"
    to_read = await load(to_read_path)
    tags = await load("/your-tags")
    to_read_count = (
        len(parse_records(to_read.html)) if _next_step(to_read.html, to_read_path) is None else None
    )
    shelves = [
        {
            "external_id": key,
            "name": label,
            "count": to_read_count if key == "to-read" else None,
            "kind": "shelf",
        }
        for key, label in SHELVES.items()
        if key != "up-next"
    ]
    upcoming = parse_records(to_read.html, only="up-next")
    if upcoming:
        shelves.append(
            {
                "external_id": "up-next",
                "name": SHELVES["up-next"],
                "count": len(upcoming),
                "kind": "shelf",
            }
        )
    shelves.extend(parse_tags(tags.html))
    return {
        "session_cookie": current["session_cookie"],
        "remember_token": cookies["remember_token"],
        "username": username,
        "shelves": shelves,
    }
