"""Private-network policy tests — synthetic DNS/HTTP fixtures only.

No real private network is contacted: DNS answers are monkeypatched and
HTTP traffic runs through httpx.MockTransport.
"""

import httpx
import pytest

from agentos import netpolicy
from agentos.netpolicy import DestinationError

pytestmark = pytest.mark.anyio


def fake_dns(answers: dict[str, list[str]]):
    """getaddrinfo stand-in: name → list of IP literals."""
    import socket as _socket

    def _getaddrinfo(host, port, family=0, type_=0, *a, **k):
        ips = answers.get(host.lower().rstrip("."))
        if ips is None:
            raise _socket.gaierror("no such host")
        return [
            (
                _socket.AF_INET6 if ":" in ip else _socket.AF_INET,
                _socket.SOCK_STREAM,
                0,
                "",
                (ip, port),
            )
            for ip in ips
        ]

    return _getaddrinfo


# -- address classification -------------------------------------------------


@pytest.mark.parametrize(
    "ip,allow_private,expected",
    [
        ("8.8.8.8", False, True),
        ("2606:4700:4700::1111", False, True),
        ("127.0.0.1", False, False),
        ("10.1.2.3", False, False),
        ("172.16.0.5", False, False),
        ("192.168.1.10", False, False),
        ("fd00::1", False, False),
        ("169.254.1.1", False, False),  # link-local — never private-eligible
        ("100.64.1.1", False, False),  # CGNAT — never private-eligible
        ("224.0.0.1", False, False),  # multicast
        ("0.0.0.0", False, False),  # unspecified
        ("::ffff:10.0.0.1", False, False),  # IPv4-mapped private
        ("127.0.0.1", True, True),
        ("10.1.2.3", True, True),
        ("fd00::1", True, True),
        ("169.254.169.254", True, False),  # cloud metadata — never
        ("fd00:ec2::254", True, False),  # AWS ULA metadata — never
        ("169.254.1.1", True, False),  # link-local stays blocked
        ("100.64.1.1", True, False),
        ("8.8.8.8", True, True),
    ],
)
def test_addr_allowed(ip, allow_private, expected):
    assert netpolicy.addr_allowed(ip, allow_private) is expected


# -- allowlist matching -----------------------------------------------------


def test_allowlist_exact_host_only():
    allow = ["Wiki.Internal.", "*.intranet", "192.168.0.5"]
    assert netpolicy.host_in_allowlist("wiki.internal", allow)
    assert netpolicy.host_in_allowlist("WIKI.INTERNAL", allow)
    assert netpolicy.host_in_allowlist("intranet", allow)  # *. normalized away
    assert netpolicy.host_in_allowlist("192.168.0.5", allow)
    assert not netpolicy.host_in_allowlist("sub.wiki.internal", allow)
    assert not netpolicy.host_in_allowlist("other.internal", allow)
    assert not netpolicy.host_in_allowlist("wiki.internal", [])


# -- URL validation ---------------------------------------------------------


def test_validate_fetch_url_accepts_plain_http():
    url = netpolicy.validate_fetch_url("https://example.com/path?q=1")
    assert url.host == "example.com"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/x",
        "http://user:pass@example.com/",
        "http://example.com\\@evil.com/",
        "not a url",
        "",
        "   ",
        "http://",
        "http://example.com:0/",
        "http://example.com:99999/",
    ],
)
def test_validate_fetch_url_rejects(url):
    with pytest.raises(DestinationError):
        netpolicy.validate_fetch_url(url)


# -- resolution policy ------------------------------------------------------


async def test_resolve_denies_private_by_default(monkeypatch):
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", fake_dns({"internal.lan": ["10.0.0.5"]}))
    with pytest.raises(DestinationError, match="private"):
        await netpolicy._resolve_checked("internal.lan", 443, False, [])


async def test_resolve_denies_mixed_answers(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        fake_dns({"flap.example": ["8.8.8.8", "192.168.1.1"]}),
    )
    with pytest.raises(DestinationError):
        await netpolicy._resolve_checked("flap.example", 443, False, [])


async def test_resolve_allowlist_grants_private(monkeypatch):
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", fake_dns({"wiki.lan": ["192.168.1.5"]}))
    ip = await netpolicy._resolve_checked("wiki.lan", 443, False, ["wiki.lan"])
    assert ip == "192.168.1.5"


async def test_resolve_allowlist_still_denies_metadata(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        fake_dns({"sneaky.lan": ["169.254.169.254"]}),
    )
    with pytest.raises(DestinationError):
        await netpolicy._resolve_checked("sneaky.lan", 443, False, ["sneaky.lan"])


async def test_resolve_literal_ip(monkeypatch):
    ip = await netpolicy._resolve_checked("8.8.8.8", 443, False, [])
    assert ip == "8.8.8.8"
    with pytest.raises(DestinationError):
        await netpolicy._resolve_checked("127.0.0.1", 443, False, [])


# -- policy_fetch -----------------------------------------------------------


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "agentos.netpolicy.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )


async def test_fetch_simple(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket, "getaddrinfo", fake_dns({"example.com": ["93.184.216.34"]})
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, text="hello")

    mock_http(monkeypatch, handle)
    final, resp, body = await netpolicy.policy_fetch("https://example.com/a")
    assert str(final) == "https://example.com/a"
    assert resp.status_code == 200
    assert body == b"hello"
    # Dialed the validated IP directly, original authority preserved.
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"


async def test_fetch_follows_redirect_revalidated(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        fake_dns({"a.com": ["8.8.8.8"], "b.com": ["1.1.1.1"]}),
    )

    def handle(request):
        if request.url.host == "8.8.8.8":
            return httpx.Response(301, headers={"location": "https://b.com/final"})
        return httpx.Response(200, text="landed")

    mock_http(monkeypatch, handle)
    final, resp, body = await netpolicy.policy_fetch("http://a.com/")
    assert str(final) == "https://b.com/final"
    assert body == b"landed"


async def test_fetch_blocks_redirect_to_private(monkeypatch):
    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        fake_dns({"a.com": ["8.8.8.8"], "internal.lan": ["10.0.0.9"]}),
    )

    def handle(request):
        return httpx.Response(302, headers={"location": "http://internal.lan/x"})

    mock_http(monkeypatch, handle)
    with pytest.raises(DestinationError, match="private"):
        await netpolicy.policy_fetch("http://a.com/")


async def test_fetch_redirect_loop_capped(monkeypatch):
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", fake_dns({"a.com": ["8.8.8.8"]}))

    def handle(request):
        return httpx.Response(302, headers={"location": "/next"})

    mock_http(monkeypatch, handle)
    with pytest.raises(DestinationError, match="redirect"):
        await netpolicy.policy_fetch("http://a.com/")


async def test_fetch_body_cap(monkeypatch):
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", fake_dns({"a.com": ["8.8.8.8"]}))

    def handle(request):
        return httpx.Response(200, content=b"x" * (netpolicy.MAX_BODY_BYTES + 1))

    mock_http(monkeypatch, handle)
    with pytest.raises(DestinationError, match="5 MB"):
        await netpolicy.policy_fetch("http://a.com/")


async def test_fetch_allowlist_permits_local_service(monkeypatch):
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", fake_dns({"wiki.lan": ["192.168.1.5"]}))

    def handle(request):
        assert request.headers["host"] == "wiki.lan"
        return httpx.Response(200, text="intranet page")

    mock_http(monkeypatch, handle)
    final, resp, body = await netpolicy.policy_fetch("http://wiki.lan/page", allowlist=["wiki.lan"])
    assert body == b"intranet page"


# -- web_fetch tool integration ---------------------------------------------


async def test_web_fetch_blocks_private_destination(monkeypatch):
    from agentos.capabilities.tools.web import web_fetch

    monkeypatch.setattr(
        netpolicy.socket, "getaddrinfo", fake_dns({"metadata.svc": ["169.254.169.254"]})
    )
    result = await web_fetch({"url": "http://metadata.svc/latest/meta-data"})
    assert result["error"].startswith("Fetch blocked:")


async def test_web_fetch_reports_landed_url(monkeypatch):
    from agentos.capabilities.tools.web import web_fetch

    monkeypatch.setattr(
        netpolicy.socket,
        "getaddrinfo",
        fake_dns({"a.com": ["8.8.8.8"], "b.com": ["1.1.1.1"]}),
    )

    def handle(request):
        if request.url.host == "8.8.8.8":
            return httpx.Response(301, headers={"location": "https://b.com/page"})
        return httpx.Response(200, text="plain content")

    mock_http(monkeypatch, handle)
    result = await web_fetch({"url": "http://a.com/start"})
    assert result["url"] == "https://b.com/page"
    assert result["content"] == "plain content"
