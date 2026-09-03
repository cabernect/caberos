"""Capability discovery tools for progressive schema loading."""

from typing import Any


async def capabilities_search(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search permitted capabilities without returning parameter schemas."""
    catalog = kwargs.get("capability_catalog")
    if catalog is None:
        return {"error": "Capability discovery is unavailable", "results": [], "count": 0}

    query = args.get("query", "")
    server = args.get("server")
    kind = args.get("kind")
    limit = args.get("limit", 20)
    results = await catalog.search(query, server=server, kind=kind, limit=limit)
    return {"query": query, "results": results, "count": len(results)}


async def capabilities_load(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Load permitted capability schemas for the next model turn."""
    catalog = kwargs.get("capability_catalog")
    if catalog is None:
        return {
            "accepted": [],
            "rejected": [{"reason": "Capability discovery is unavailable"}],
            "loaded": [],
        }

    names = args.get("names", [])
    if not isinstance(names, list):
        return {
            "accepted": [],
            "rejected": [{"reason": "names must be a list"}],
            "loaded": sorted(catalog.loaded),
        }
    return await catalog.load([name for name in names if isinstance(name, str)])
