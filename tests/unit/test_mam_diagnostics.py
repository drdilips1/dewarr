import asyncio

import httpx

from app.domain.mam_diagnostics import probe_egress


async def test_ip_probe_fallback_is_credential_free_and_validates_ip():
    calls = []

    def handler(request):
        calls.append(request)
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200, text="not an IP" if len(calls) == 1 else "2001:db8::1\n")

    result = await probe_egress(transport=httpx.MockTransport(handler))
    assert result.ip == "2001:db8::1" and result.error is None
    assert len(calls) == 2


async def test_ip_probe_rejects_large_or_redirected_responses():
    for response in [httpx.Response(200, text="x" * 300), httpx.Response(302)]:
        result = await probe_egress(
            transport=httpx.MockTransport(lambda _, response=response: response)
        )
        assert result.ip is None and result.error


async def test_proxy_probe_never_falls_back_direct_or_leaks_credentials():
    calls = []

    async def proxy(reader, writer):
        calls.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 407 private-error\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with await asyncio.start_server(proxy, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        result = await probe_egress(f"http://127.0.0.1:{port}", "private-user", "secret")
    assert len(calls) == 2
    assert all(b"CONNECT " in call and b"Proxy-Authorization: Basic" in call for call in calls)
    assert result.ip is None
    assert "private" not in result.error and "secret" not in result.error
