"""Knowledge Vault capabilities."""

from typing import Any

from ...knowledge.ingest import search_documents


async def doc_search(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search shared knowledge and the active agent's private knowledge."""
    query = args["query"]
    limit = args.get("limit", 5)
    results = await search_documents(
        kwargs["db"],
        query,
        limit=limit,
        agent_id=kwargs["agent_id"],
    )
    return {"query": query, "results": results, "count": len(results)}
