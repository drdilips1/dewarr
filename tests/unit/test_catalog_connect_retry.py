import httpx
import pytest

from app.adapters.contracts import AdapterError
from app.adapters.http import JsonEndpoint
from app.domain.catalog_network import CatalogGateway


def gateway(handler):
    value = object.__new__(CatalogGateway)
    value.http = JsonEndpoint(
        "https://catalog.test", "token", transport=httpx.MockTransport(handler)
    )
    return value


async def test_dropped_connections_are_retried_but_answered_failures_are_not(monkeypatch):
    sleeps = []

    async def no_wait(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.domain.catalog_network.asyncio.sleep", no_wait)
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise httpx.ConnectTimeout("dropped", request=request)
        return httpx.Response(200, json={"data": {"ok": True}})

    assert await gateway(flaky).send("POST", "graphql", None, {"query": "q"}) == {
        "data": {"ok": True}
    }
    assert len(attempts) == 3 and sleeps == [1.0, 2.0]

    attempts.clear()

    def down(request):
        attempts.append(request)
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AdapterError):
        await gateway(down).send("POST", "graphql", None, {"query": "q"})
    assert len(attempts) == 3

    attempts.clear()

    def answered(request):
        attempts.append(request)
        return httpx.Response(503)

    with pytest.raises(AdapterError):
        await gateway(answered).send("POST", "graphql", None, {"query": "q"})
    assert len(attempts) == 1
