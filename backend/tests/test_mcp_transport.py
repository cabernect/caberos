"""Connection-policy fixtures through HTTPX2, with no real DNS or connections."""

import socket

import httpx2
import pytest

from agentos import netpolicy
from agentos.mcp.transport import PolicyTransport


@pytest.fixture(autouse=True)
def controlled_dns(monkeypatch):
    def lookup(host, port, *args):
        addresses = {"mcp.test": "8.8.8.8", "auth.test": "8.8.4.4", "localhost": "127.0.0.1"}
        assert host in addresses, "unexpected synthetic DNS destination"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], port))]

    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(netpolicy, "private_allowlist", lambda: [])


async def test_pins_dial_address_but_keeps_logical_authority_and_response_url():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json={"ok": True})

    logical = "https://mcp.test:8443/mcp"
    transport = PolicyTransport(logical, transport=httpx2.MockTransport(respond))
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        response = await client.post(
            logical,
            content=b"synthetic-body",
            headers={"Authorization": "Bearer dummy-token", "Host": "wrong.test"},
        )
    sent = requests[0]
    assert str(sent.url) == "https://8.8.8.8:8443/mcp"
    assert sent.headers["Host"] == "mcp.test:8443"
    assert sent.extensions["sni_hostname"] == "mcp.test"
    assert sent.method == "POST"
    assert sent.headers["Authorization"] == "Bearer dummy-token"
    assert str(response.request.url) == logical


@pytest.mark.parametrize("server", ["http://127.0.0.1:9000/mcp", "http://localhost:9000/mcp"])
async def test_explicit_local_server_is_allowed_but_does_not_grant_other_private_endpoints(server):
    requests = []
    transport = PolicyTransport(
        server, transport=httpx2.MockTransport(lambda r: requests.append(r) or httpx2.Response(200))
    )
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        await client.get(server)
        with pytest.raises(netpolicy.DestinationError):
            await client.get("http://127.0.0.1:8081/api/settings")
        with pytest.raises(netpolicy.DestinationError):
            await client.get(server.replace(":9000", ":9001"))
    assert len(requests) == 1


@pytest.mark.parametrize("address", ["169.254.169.254", "[fd00:ec2::254]"])
async def test_metadata_is_denied_even_when_configured_as_the_server(address):
    requests = []
    server = f"http://{address}/mcp"
    transport = PolicyTransport(
        server, transport=httpx2.MockTransport(lambda r: requests.append(r) or httpx2.Response(200))
    )
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(netpolicy.DestinationError):
            await client.get(server)
    assert requests == []


async def test_public_server_does_not_implicitly_authorize_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    requests = []
    transport = PolicyTransport(
        "https://mcp.test/mcp",
        transport=httpx2.MockTransport(lambda r: requests.append(r) or httpx2.Response(200)),
    )
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(netpolicy.DestinationError):
            await client.get("https://mcp.test/mcp")
    assert requests == []


async def test_each_followed_redirect_is_checked_before_the_next_connection():
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx2.Response(307, headers={"Location": "http://127.0.0.1:8081/private"})

    transport = PolicyTransport("https://mcp.test/mcp", transport=httpx2.MockTransport(redirect))
    async with httpx2.AsyncClient(
        transport=transport, trust_env=False, follow_redirects=True
    ) as client:
        with pytest.raises(netpolicy.DestinationError):
            await client.get("https://mcp.test/mcp")
    assert len(requests) == 1


async def test_existing_operator_allowlist_applies_without_new_permission_fields(monkeypatch):
    monkeypatch.setattr(netpolicy, "private_allowlist", lambda: ["localhost"])
    requests = []
    transport = PolicyTransport(
        "https://mcp.test/mcp",
        transport=httpx2.MockTransport(lambda r: requests.append(r) or httpx2.Response(200)),
    )
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        await client.get("http://localhost:9001/discovery")
    assert requests[0].url.host == "127.0.0.1"


async def test_inner_transport_is_closed_with_the_client():
    class ControlledTransport(httpx2.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request):
            return httpx2.Response(200)

        async def aclose(self):
            self.closed = True

    inner = ControlledTransport()
    async with httpx2.AsyncClient(
        transport=PolicyTransport("https://mcp.test/mcp", transport=inner), trust_env=False
    ) as client:
        await client.get("https://mcp.test/mcp")
    assert inner.closed


async def test_logical_origins_keep_cookies_separate_even_on_the_same_ip(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, headers={"Set-Cookie": "session=dummy; Path=/"})

    transport = PolicyTransport("https://mcp.test/mcp", transport=httpx2.MockTransport(respond))
    async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
        await client.get("https://mcp.test/mcp")
        await client.get("https://auth.test/discovery")
    assert [r.url.host for r in requests] == ["8.8.8.8", "8.8.8.8"]
    assert "Cookie" not in requests[1].headers
