import httpx
import pytest

from app.adapters.contracts import AdapterError
from app.adapters.qbittorrent import QbitClient
from tests.unit.test_qbittorrent_adapter import files, properties, row


class CensusServer:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.mutate = None
        self.pages = 0
        self.file_rows = {}

    async def handle(self, request):
        self.calls.append((request.method, request.url.path))
        path = request.url.path.split("/api/v2/", 1)[-1]
        if path == "auth/login":
            return httpx.Response(200, text="Ok.")
        assert request.method == "GET"
        if path == "app/version":
            return httpx.Response(200, text="v5.2.3")
        if path == "app/webapiVersion":
            return httpx.Response(200, text="2.15.1")
        if path == "torrents/info":
            if "hashes" in request.url.params:
                values = [r for r in self.rows if r["hash"] == request.url.params["hashes"]]
            elif "tag" in request.url.params:
                values = [
                    r
                    for r in self.rows
                    if request.url.params["tag"] in {tag.strip() for tag in r["tags"].split(",")}
                ]
            else:
                self.pages += 1
                if self.mutate:
                    self.mutate(self)
                assert request.url.params["sort"] == "hash"
                start = int(request.url.params["offset"])
                values = sorted(self.rows, key=lambda r: r["hash"])[start : start + 250]
            return httpx.Response(200, json=values)
        if path == "torrents/properties":
            selected = next(r for r in self.rows if r["hash"] == request.url.params["hash"])
            return httpx.Response(
                200, json=properties(infohash_v1=selected["hash"], save_path=selected["save_path"])
            )
        if path == "torrents/files":
            return httpx.Response(200, json=self.file_rows.get(request.url.params["hash"], files()))
        raise AssertionError(path)

    def client(self, endpoint="http://qbit.test", username="fixture", password="secret"):
        return QbitClient(endpoint, username, password, transport=httpx.MockTransport(self.handle))


def transfer(index=1, **changes):
    return row(
        **{
            "hash": f"{index:040x}",
            "save_path": "/downloads/books",
            "added_on": 100,
            "name": "Synthetic transfer",
            **changes,
        }
    )


async def pulse():
    pass


async def test_census_pages_all_transfers_and_reads_only_relevant_files():
    rows = [transfer(i, category="video", tags="unrelated") for i in range(1, 253)]
    rows[-1]["tags"] = "book-search:lost-after-backup"
    server = CensusServer(rows)
    async with server.client() as client:
        states, total = await client.census(
            known_hashes={rows[0]["hash"]}, categories={"book-search"}, pulse=pulse
        )
    assert total == 252 and len(states) == 2
    assert {s.external_id for s in states} == {rows[0]["hash"], rows[-1]["hash"]}
    assert server.pages == 9
    assert sum(path.endswith("/files") for _, path in server.calls) == 2
    assert all(method == "GET" or path.endswith("auth/login") for method, path in server.calls)


@pytest.mark.parametrize("change", ["membership", "routing", "duplicate", "final"])
async def test_changed_or_repeated_census_cannot_prove_absence(change):
    server = CensusServer([transfer()])

    def mutate(current):
        if change == "membership" and current.pages == 3:
            current.rows.append(transfer(2))
        if change == "routing" and current.pages == 3:
            current.rows[0]["save_path"] = "/elsewhere"
        if change == "duplicate" and current.pages == 1:
            current.rows.append(dict(current.rows[0]))
        if change == "final" and current.pages == 5:
            current.rows[0]["tags"] = "changed-after-file-observation"

    server.mutate = mutate
    with pytest.raises(AdapterError):
        async with server.client() as client:
            await client.census(known_hashes=set(), categories={"book-search"}, pulse=pulse)


async def test_progress_during_read_does_not_invalidate_identity_census():
    server = CensusServer([transfer()])
    server.mutate = lambda current: current.rows[0].update(progress=0.5 if current.pages < 3 else 1)
    async with server.client() as client:
        states, _ = await client.census(known_hashes=set(), categories={"book-search"}, pulse=pulse)
    assert len(states) == 1


async def test_census_normalizes_the_clients_trailing_save_path_separator():
    server = CensusServer([transfer(save_path="/downloads/books/")])
    async with server.client() as client:
        states, total = await client.census(
            known_hashes=set(), categories={"book-search"}, pulse=pulse
        )
    assert total == 1 and states[0].save_path == "/downloads/books"
