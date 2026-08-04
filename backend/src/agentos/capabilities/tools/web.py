"""Web capabilities — web_search and web_fetch.

web_search uses DuckDuckGo's HTML endpoint (free, no API key required).
web_fetch retrieves a URL and returns the text content.

Both are egress capabilities — they access the network, so they require approval
by default (the operator can disable this per-agent).
"""

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup


async def web_search(args: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Search the web using DuckDuckGo (free, no API key).

    Args:
        query: Search query
        max_results: Maximum number of results (default: 5)
    """
    query = args["query"]
    max_results = args.get("max_results", 5)

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Use DuckDuckGo's HTML endpoint — no API key needed
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "CaberOS/0.1 (local-first agent OS)"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"Search failed: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []

    # DuckDuckGo HTML results are in .result blocks
    for block in soup.select(".result"):
        title_el = block.select_one(".result__title a")
        snippet_el = block.select_one(".result__snippet")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        # DuckDuckGo wraps URLs in a redirect — extract the actual URL
        href = title_el.get("href", "")
        url_match = re.search(r"uddg=([^&]+)", href)
        url = (
            __import__("urllib.parse", fromlist=["unquote"]).unquote(url_match.group(1))
            if url_match
            else href
        )
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break

    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


async def web_fetch(args: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Fetch a URL and return its text content.

    Args:
        url: The URL to fetch
        max_chars: Maximum characters to return (default: 8000)
    """
    url = args["url"]
    max_chars = args.get("max_chars", 8000)

    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True
        ) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "CaberOS/0.1 (local-first agent OS)"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"Fetch failed: {e}"}

    # Parse HTML and extract text
    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Truncate to max_chars
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"

    return {
        "url": url,
        "content": text,
        "title": soup.title.string if soup.title else "",
    }
