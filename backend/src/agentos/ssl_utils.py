"""Shared SSL certificate path for httpx clients.

On macOS with Homebrew Python, httpx doesn't pick up the Homebrew CA bundle
by default. This is especially problematic behind corporate firewalls/proxies
that inject their own CA (e.g. FPT captive portal).

This module finds the best available CA bundle and exports it for use
across all httpx clients (channels, discovery, etc.).
"""

import os
from pathlib import Path

# Find the best SSL cert bundle — prefer Homebrew's ca-certificates (includes
# corporate/proxy CAs on macOS), then system stores, then certifi.
# Don't rely on SSL_CERT_FILE env var since it may point to a bundle
# that doesn't include corporate CAs.
SSL_CERT_PATH: str | None = None
for _candidate in (
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/ca-certificates/cert.pem",
    "/usr/local/etc/ssl/cert.pem",
    "/etc/ssl/cert.pem",
):
    if os.path.exists(_candidate):
        SSL_CERT_PATH = _candidate
        break
if not SSL_CERT_PATH:
    import certifi

    SSL_CERT_PATH = certifi.where()
