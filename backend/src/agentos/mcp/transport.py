"""MCP's HTTP adapter for the shared outbound destination policy.

The logical request URL remains unchanged for OAuth, cookies, and redirects.
Only the transport's dial URL is pinned. Every SDK-generated request traverses
this adapter, including discovery, registration, token exchange, and refresh.
"""

import asyncio
import ipaddress
import math

import httpx
import httpx2

from .. import netpolicy


def _origin(url: httpx.URL | httpx2.URL) -> tuple[str, str, int]:
    return (url.scheme, url.host, url.port or (443 if url.scheme == "https" else 80))


class PolicyTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self,
        server_url: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        server = netpolicy.validate_fetch_url(server_url)
        try:
            ipaddress.ip_address(server.host)
            local = netpolicy.addr_allowed(server.host, True) and not netpolicy.addr_allowed(
                server.host, False
            )
        except ValueError:
            local = server.host.lower().rstrip(".") == "localhost"
        self._local_origin = _origin(server) if local else None
        self._transport = (
            transport
            if transport is not None
            else httpx2.AsyncHTTPTransport(
                trust_env=False, limits=httpx2.Limits(max_keepalive_connections=0)
            )
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        logical = netpolicy.validate_fetch_url(str(request.url))
        # Literal local/localhost configuration authorizes that exact origin,
        # not other private endpoints or a public hostname rebinding to LAN.
        allow_private = _origin(logical) == self._local_origin
        connect_timeout = request.extensions.get("timeout", {}).get("connect")
        deadline = 30.0 if connect_timeout is None else float(connect_timeout)
        if not math.isfinite(deadline) or deadline <= 0:
            raise httpx2.ConnectTimeout("Destination resolution requires a finite deadline.")
        try:
            async with asyncio.timeout(deadline):
                logical, address = await netpolicy.resolve_destination(
                    str(logical),
                    allow_private=allow_private,
                    allowlist=netpolicy.private_allowlist(),
                )
        except TimeoutError:
            raise httpx2.ConnectTimeout("Destination resolution exceeded its deadline.") from None
        headers = request.headers.copy()
        headers["Host"] = logical.netloc.decode("ascii")
        if "Proxy-Authorization" in headers:
            del headers["Proxy-Authorization"]
        extensions = {**request.extensions, "sni_hostname": logical.host}
        # SDK-generated auth requests may not carry the client's timeout
        # extension. They must not become unbounded transport operations.
        extensions.setdefault(
            "timeout", {phase: deadline for phase in ("connect", "read", "write", "pool")}
        )
        dial = httpx2.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._transport.handle_async_request(dial)

    async def aclose(self) -> None:
        await self._transport.aclose()
