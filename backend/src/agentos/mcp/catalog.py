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
    with open(CATALOG_PATH) as f:
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


def list_categories() -> list[dict[str, int]]:
    """List categories with server counts."""
    entries = _load_catalog()
    counts: dict[str, int] = {}
    for e in entries:
        cat = e.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]
