"""Operator-configured Firecrawl origins, with consent checked at the dial target."""

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..netpolicy import addr_allowed as _address_allowed

SELF_HOSTED = "firecrawl_self_hosted"


def validate_self_hosted(
    base_url: str | None, options: dict[str, Any] | None
) -> tuple[str, dict[str, bool]]:
    """Local-only validation: saving never resolves DNS or contacts the server."""
    options = {} if options is None else options
    if not isinstance(options, dict):
        raise ValueError("Self-hosted options must be an object.")
    if set(options) - {"allow_private_network"}:
        raise ValueError("Only allow_private_network is supported for a self-hosted connection.")
    allow_private = options.get("allow_private_network", False)
    if not isinstance(allow_private, bool):
        raise ValueError("allow_private_network must be a boolean.")
    value = (base_url or "").strip()
    if not value or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError("Enter a valid self-hosted Firecrawl server URL.")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or "\\" in value
            or "%" in value
            or ".." in parts.path
            or (parts.port is not None and not 1 <= parts.port <= 65535)
        ):
            raise ValueError
    except ValueError:
        raise ValueError(
            "Use an HTTP(S) server URL without credentials, query, or fragment."
        ) from None
    host = parts.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host.lower().rstrip(".") == "localhost" and not allow_private:
            raise ValueError("Private-network access requires explicit consent for this server.")
    else:
        if not _address_allowed(host, allow_private):
            raise ValueError("This address is blocked or requires private-network consent.")
    # Accept a copied /v2 base URL without accidentally producing /v2/v2/search.
    path = parts.path.rstrip("/")
    if path.endswith("/v2"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")), {
        "allow_private_network": allow_private
    }


async def pinned_self_hosted_url(
    base_url: str, options: dict[str, Any]
) -> tuple[httpx.URL, dict[str, str], dict[str, Any]]:
    """Resolve once, validate every answer, then dial one IP with original Host/SNI."""
    base_url, options = validate_self_hosted(base_url, options)
    url = httpx.URL(base_url + "/v2/search")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo,
        url.host,
        url.port or (443 if url.scheme == "https" else 80),
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
    )
    ips = {entry[4][0] for entry in addresses}
    if not ips or not all(_address_allowed(ip, options["allow_private_network"]) for ip in ips):
        raise ValueError("The self-hosted server resolved to a blocked or unapproved address.")
    if url.scheme == "http" and any(ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Public self-hosted servers must use HTTPS.")
    # Prefer IPv4 when localhost resolves to both families but the service only
    # listens on 127.0.0.1. No second DNS lookup or alternate-address retry.
    selected = sorted(ips, key=lambda ip: (ipaddress.ip_address(ip).version, ip))[0]
    authority = url.netloc.decode("ascii")
    return url.copy_with(host=selected), {"Host": authority}, {"sni_hostname": url.host}
