"""MCP catalog — loads the static catalog.yaml and serves it via API.

The catalog is a curated list of official MCP servers. Operators browse
the catalog and install servers with one click — no need to manually
enter command/args.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).parent / "catalog.yaml"


@lru_cache(maxsize=1)
def _load_catalog() -> list[dict[str, Any]]:
    """Load and cache the catalog YAML."""
    # encoding is explicit: Python on Windows defaults to the locale
    # codepage (cp1252), which mangles the em-dashes in this catalog.
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("servers", [])


def list_catalog_entries(
    category: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """List catalog entries, optionally filtered by category or search query."""
    entries = _load_catalog()

    if category:
        entries = [e for e in entries if e.get("category") == category]

    if query:
        q = query.lower()
        entries = [
            e
            for e in entries
            if q in e.get("name", "").lower()
            or q in e.get("description", "").lower()
            or q in e.get("category", "").lower()
        ]

    return entries


def get_catalog_entry(name: str) -> dict[str, Any] | None:
    """Get a single catalog entry by name."""
    for entry in _load_catalog():
        if entry.get("name") == name:
            return entry
    return None


def api_key_headers(name: str, transport: str, url: str | None) -> dict[str, str]:
    """Recover omitted templates for legacy installs, never for a different endpoint."""
    entry = get_catalog_entry(name)
    entry_url = (entry or {}).get("url")
    # Query markers (e.g. Exa's ?login) select the auth mode, not a different
    # endpoint — matching on the path keeps template recovery working when a
    # server was installed against either variant.
    same_endpoint = (
        url is not None and entry_url is not None and url.split("?")[0] == entry_url.split("?")[0]
    )
    if (
        entry
        and transport == entry.get("transport") == "http"
        and same_endpoint
        and any("{{credential" in v for v in (entry.get("headers") or {}).values())
    ):
        return dict(entry["headers"])
    return {}


def list_categories() -> list[dict[str, int]]:
    """List categories with server counts."""
    entries = _load_catalog()
    counts: dict[str, int] = {}
    for e in entries:
        cat = e.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]
