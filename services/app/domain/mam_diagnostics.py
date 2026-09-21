"""Credential-free public egress probes, independent of the rotating MAM session."""

import asyncio
from ipaddress import ip_address

import httpx
from pydantic import BaseModel


class EgressResult(BaseModel):
    ip: str | None = None
    error: str | None = None


async def probe_egress(proxy_url=None, username=None, password=None, *, transport=None):
    proxy = (
        httpx.Proxy(proxy_url, auth=(username or "", password or ""))
        if proxy_url and (username or password)
        else proxy_url
    )
    try:
        async with (
            asyncio.timeout(12),
            httpx.AsyncClient(
                proxy=proxy,
                trust_env=False,
                follow_redirects=False,
                timeout=5,
                transport=transport,
            ) as client,
        ):
            for url in ("https://api.ipify.org", "https://icanhazip.com"):
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 256:
                                raise ValueError("Invalid IP response")
                    return EgressResult(ip=str(ip_address(body.decode().strip())))
                except (httpx.HTTPError, ValueError, UnicodeError):
                    continue
    except (httpx.HTTPError, TimeoutError):
        pass
    return EgressResult(error="Public IP lookup failed. Check the route and try again.")
