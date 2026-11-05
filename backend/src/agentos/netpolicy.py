"""Shared outbound-destination policy for agent-driven HTTP requests.

One classification authority for "may this request leave the machine":

- Ordinary global unicast addresses are allowed; IPv6 translation/tunnel
  ranges are unsupported.
- Loopback and RFC1918/ULA destinations are allowed only through an explicit
  exception — an operator allowlist entry naming that exact host, or a
  caller-granted ``allow_private`` flag (self-hosted service connections).
- Link-local, multicast, reserved, unspecified, CGNAT, and cloud-metadata
  addresses are never allowed, even under an exception.

Enforcement dials a resolved, validated IP directly (original ``Host`` header
and SNI preserved) and re-validates at every redirect hop, so DNS answers are
checked at connection time rather than trusted from a preflight lookup.
"""

import asyncio
import ipaddress
import math
import socket
from urllib.parse import urlsplit

import httpx

_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
_UNSUPPORTED_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)

# Cloud metadata endpoints — never admitted, even under a private exception.
# AWS IMDS also answers on a ULA address, so a private opt-in must not admit it.
_BLOCKED_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})

_MAX_REDIRECTS = 5
# Bodies are read bounded — a hostile or misbehaving endpoint cannot stream
# unbounded content into the run context or memory.
MAX_BODY_BYTES = 5 * 1024 * 1024
_FETCH_HEADER_NAMES = frozenset({"user-agent", "accept", "accept-language", "range"})


class DestinationError(ValueError):
    """Raised when a URL or its resolved destination is not permitted.

    The message is operator-facing: it explains the block without echoing
    request content or credentials.
    """


def addr_allowed(value: str, allow_private: bool) -> bool:
    """True when an IP literal is permitted under the private-access flag."""
    ip = ipaddress.ip_address(value)
    ip = getattr(ip, "ipv4_mapped", None) or ip
    if str(ip) in _BLOCKED_ADDRESSES:
        return False
    if (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.is_reserved and not ip.is_loopback)
    ):
        return False
    # is_global alone admits some reserved/site-local IPv6 ranges. Translation
    # and tunnel addresses also carry another destination that this policy
    # does not validate, so refuse them rather than treating them as public.
    if isinstance(ip, ipaddress.IPv6Address) and (
        ip.is_site_local or any(ip in network for network in _UNSUPPORTED_IPV6_NETWORKS)
    ):
        return False
    if ip.is_global and not ip.is_multicast:
        return True
    return allow_private and (
        ip.is_loopback
        or any(ip.version == network.version and ip in network for network in _PRIVATE_NETWORKS)
    )


def host_in_allowlist(host: str, allowlist: list[str] | tuple[str, ...] | None) -> bool:
    """Exact-host exception match — an entry names one hostname or IP literal.

    Subdomains are not implied: allowing ``wiki.internal`` does not open
    ``db.wiki.internal``. Entries are compared case-insensitively with
    trailing dots normalized away. Wildcard entries are never interpreted.
    """
    normalized = host.lower().rstrip(".")
    for entry in allowlist or ():
        candidate = str(entry).strip().lower().rstrip(".")
        if normalized == candidate:
            return True
    return False


def validate_fetch_url(url: str) -> httpx.URL:
    """Parse and restrict a fetch URL to plain HTTP(S) with no credentials."""
    value = (url or "").strip()
    if (
        not value
        or len(value) > 4096
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise DestinationError("Enter a valid http(s) URL.")
    try:
        parts = urlsplit(value)
        port = parts.port  # raises ValueError on out-of-range/non-numeric ports
    except ValueError:
        raise DestinationError("Enter a valid http(s) URL.") from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or "\\" in value
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise DestinationError("Use an http(s) URL without credentials.")
    host = parts.hostname
    if not host or len(host) > 253 or "%" in host:
        raise DestinationError("Enter a valid http(s) URL.")
    try:
        return httpx.URL(value)
    except httpx.InvalidURL:
        raise DestinationError("Enter a valid http(s) URL.") from None


async def _resolve_checked(
    host: str, port: int, allow_private: bool, allowlist: list[str] | None
) -> str:
    """Resolve once and require every answer to be a permitted address.

    A name granted a private exception resolves freely; every other name must
    yield only public addresses — a single private answer in a mixed response
    fails the whole name.
    """
    permitted = allow_private or host_in_allowlist(host, allowlist)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
        except socket.gaierror:
            raise DestinationError("The host could not be resolved.") from None
        ips = {entry[4][0] for entry in answers}
        if not ips:
            raise DestinationError("The host could not be resolved.")
    else:
        ips = {host}
    if not all(addr_allowed(ip, permitted) for ip in ips):
        raise DestinationError(
            "This URL resolves to a local or private-network address. "
            "Add the hostname to the private-network allowlist in Settings to allow it."
        )
    # Prefer IPv4 so dual-stack names hit a listening family.
    return sorted(ips, key=lambda ip: (ipaddress.ip_address(ip).version, ip))[0]


async def _pinned_get(
    client: httpx.AsyncClient,
    url: httpx.URL,
    *,
    allow_private: bool,
    allowlist: list[str] | None,
    headers: httpx.Headers | dict[str, str],
) -> tuple[httpx.Response, bytes]:
    """One request hop: resolve+check, then dial the validated IP directly."""
    host = url.host
    port = url.port or (443 if url.scheme == "https" else 80)
    pinned_ip = await _resolve_checked(host, port, allow_private, allowlist)
    dial = url.copy_with(host=pinned_ip)
    request_headers = httpx.Headers(headers)
    request_headers["Host"] = url.netloc.decode("ascii")
    request_headers["Accept-Encoding"] = "identity"
    # The transport URL uses an IP: a cookie jar keyed by that IP could
    # otherwise carry one origin's cookies to another origin on the same IP.
    client.cookies.clear()
    async with client.stream(
        "GET",
        dial,
        headers=request_headers,
        extensions={"sni_hostname": host},
    ) as response:
        if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
            raise DestinationError("Encoded fetch responses are not supported.")
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise DestinationError("Response exceeded the 5 MB fetch limit.")
        return response, bytes(body)


async def policy_fetch(
    url: str,
    *,
    allowlist: list[str] | None = None,
    allow_private: bool = False,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    verify: str | bool = True,
) -> tuple[httpx.URL, httpx.Response, bytes]:
    """Fetch a URL under destination policy.

    Every hop — the original URL and each redirect target — is re-validated
    and re-resolved before connecting. Returns ``(final_url, response, body)``;
    callers decide how to treat non-2xx statuses.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise DestinationError("Fetch requires a positive finite deadline.")
    request_headers = httpx.Headers(headers)
    if any(name not in _FETCH_HEADER_NAMES for name in request_headers):
        raise DestinationError(
            "Generic fetching accepts only public content headers, not credentials."
        )
    target = validate_fetch_url(url)
    try:
        # httpx's inactivity timeouts alone do not bound DNS, slow streams,
        # or a redirect chain. This deadline covers the whole operation.
        async with (
            asyncio.timeout(timeout),
            httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, verify=verify, trust_env=False
            ) as client,
        ):
            for _ in range(_MAX_REDIRECTS + 1):
                response, body = await _pinned_get(
                    client,
                    target,
                    allow_private=allow_private,
                    allowlist=allowlist,
                    headers=request_headers,
                )
                if response.is_redirect and response.headers.get("location"):
                    try:
                        joined = str(target.join(response.headers["location"]))
                    except (httpx.InvalidURL, ValueError):
                        raise DestinationError("Invalid redirect destination.") from None
                    target = validate_fetch_url(joined)
                    continue
                return target, response, body
    except TimeoutError:
        raise httpx.TimeoutException("Fetch exceeded its total deadline.") from None
    raise DestinationError("Too many redirects.")


def private_allowlist() -> list[str]:
    """Operator-granted private-network exceptions for general web fetch."""
    from .config import settings

    value = getattr(settings, "web_private_allowlist", None)
    return list(value) if isinstance(value, list) else []
