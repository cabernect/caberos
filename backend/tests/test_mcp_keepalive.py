"""Regression tests for the poisoned keep-alive OAuth failure.

Some MCP servers (observed: mcp.tradingview.com) answer a POST /mcp with
401 + `Connection: keep-alive` and then immediately close the socket. A
pooled httpx2 client reuses that connection for the protected-resource
metadata GET and dies with `RemoteProtocolError: Server disconnected
without sending a response` — so OAuth can never produce an authorize URL.

Fix: the OAuth-flow client and the streamable-HTTP transport client are
built with `limits=httpx2.Limits(max_keepalive_connections=0)`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx2
import pytest

from agentos.mcp.client import _ensure_user_agent


async def _read_request(reader: asyncio.StreamReader) -> None:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(4096)
        if not chunk:
            return
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    clen = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            clen = int(line.split(b":", 1)[1].strip())
    while len(body) < clen:
        chunk = await reader.read(4096)
        if not chunk:
            return
        body += chunk


async def _rude_server() -> tuple[asyncio.AbstractServer, int]:
    """TCP server: 1st connection gets a keep-alive 401, then swallows the
    next request and closes — the poisoned-pool pattern observed from
    mcp.tradingview.com. The next connection gets a normal 200."""

    conns = 0

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal conns
        await _read_request(reader)
        conns += 1
        if conns == 1:
            payload = b'{"detail":"oauth required"}'
            resp = (
                b"HTTP/1.1 401 Unauthorized\r\n"
                b"Content-Type: application/json\r\n"
                b"Connection: keep-alive\r\n"
                b'WWW-Authenticate: Bearer resource_metadata="http://x/.well-known"\r\n'
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                + payload
            )
            writer.write(resp)
            await writer.drain()
            try:
                # Keep the socket nominally alive; when the client reuses the
                # pooled connection, swallow the request and drop the socket.
                await asyncio.wait_for(_read_request(reader), timeout=5.0)
            except TimeoutError:
                pass
            writer.close()
            await writer.wait_closed()
        else:
            payload = b'{"ok":true}'
            resp = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            writer.write(resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_pooled_client_fails_on_401_then_close():
    """Control case: a pooled client reusing the closed connection dies with
    RemoteProtocolError — the exact failure seen against tradingview."""
    server, port = await _rude_server()
    try:
        async with httpx2.AsyncClient(timeout=5.0) as client:
            r1 = await client.post(
                f"http://127.0.0.1:{port}/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            )
            assert r1.status_code == 401
            with pytest.raises(httpx2.RemoteProtocolError):
                await client.get(f"http://127.0.0.1:{port}/.well-known/prm")
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_no_keepalive_client_survives_401_then_close():
    """With keep-alive pooling disabled the metadata GET goes out on a fresh
    connection and succeeds."""
    server, port = await _rude_server()
    try:
        async with httpx2.AsyncClient(
            timeout=5.0,
            limits=httpx2.Limits(max_keepalive_connections=0),
        ) as client:
            r1 = await client.post(
                f"http://127.0.0.1:{port}/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            )
            assert r1.status_code == 401
            r2 = await client.get(f"http://127.0.0.1:{port}/.well-known/prm")
            assert r2.status_code == 200
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_oauth_flow_client_disables_keepalive(monkeypatch):
    """_run_oauth_flow must build its client without connection reuse."""
    from agentos.mcp.oauth import OAuthFlowState, _run_oauth_flow

    recorded: dict = {}
    real_cls = httpx2.AsyncClient

    def _spy(*args, **kwargs):
        recorded.update(kwargs)
        kwargs["transport"] = httpx2.MockTransport(
            lambda req: httpx2.Response(401, json={"detail": "no"})
        )
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", _spy)

    auth = SimpleNamespace(
        context=SimpleNamespace(protected_resource_metadata=None, oauth_metadata=None)
    )
    flow = OAuthFlowState("srv-x")
    # _connect_after_oauth would fail on an unknown server — irrelevant; we
    # only need the client construction. The trailing 10s cleanup sleep is
    # cancelled by wait_for's timeout.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            _run_oauth_flow("srv-x", "http://127.0.0.1:9/mcp", auth, flow),
            timeout=2.0,
        )

    limits = recorded.get("limits")
    assert isinstance(limits, httpx2.Limits)
    assert limits.max_keepalive_connections == 0
    hooks = recorded.get("event_hooks") or {}
    assert _ensure_user_agent in hooks.get("request", [])


@pytest.mark.asyncio
async def test_http_transport_client_disables_keepalive(monkeypatch):
    """The streamable-HTTP transport client must also disable reuse — an
    expired-token refresh inside it hits the same poisoned-connection race."""
    import mcp as mcp_pkg
    import mcp.client.streamable_http as sh

    from agentos.mcp.client import McpClient

    recorded: dict = {}
    real_cls = httpx2.AsyncClient

    def _spy(*args, **kwargs):
        recorded.update(kwargs)
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", _spy)

    @asynccontextmanager
    async def _fake_transport(url, http_client=None):
        yield (object(), object())

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            return None

    monkeypatch.setattr(sh, "streamable_http_client", _fake_transport)
    monkeypatch.setattr(mcp_pkg, "ClientSession", _FakeSession)

    client = McpClient(transport="http", url="http://127.0.0.1:9/mcp", timeout=5.0)
    await client.connect()
    try:
        assert client.connected
        limits = recorded.get("limits")
        assert isinstance(limits, httpx2.Limits)
        assert limits.max_keepalive_connections == 0
        hooks = recorded.get("event_hooks") or {}
        assert _ensure_user_agent in hooks.get("request", [])
    finally:
        await client.disconnect()
