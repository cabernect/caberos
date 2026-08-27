"""Web capabilities — web_search and web_fetch.

web_search uses the ddgs package (free, no API key required).
web_fetch retrieves a URL and returns the text content.

Both are egress capabilities — they access the network, so they require approval
by default (the operator can disable this per-agent).
"""

import asyncio
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from ...models.web_source import WebSource
from ...ssl_utils import SSL_CERT_PATH


async def web_search(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Search the web using DuckDuckGo (free, no API key).

    Args:
        query: Search query
        max_results: Maximum number of results (default: 5)
    """
    query = args["query"]
    max_results = args.get("max_results", 5)

    try:
        from ddgs import DDGS

        def _sync_search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                # Try engines in order — DuckDuckGo first (most reliable
                # through corporate proxies), then Bing, Startpage, Brave.
                for engine in ("duckduckgo", "bing", "startpage", "brave"):
                    try:
                        return list(ddgs.text(query, max_results=max_results, engine=engine))
                    except Exception:
                        continue
                return []

        results = await asyncio.to_thread(_sync_search)
    except ImportError:
        # Fallback: raw HTML scraping (may hit captcha pages)
        result = await _web_search_html(query, max_results)
        await _persist_web_sources(result, kwargs)
        return result
    except Exception as e:
        # Fallback: try HTML scraping if the package fails
        fallback = await _web_search_html(query, max_results)
        if fallback.get("count", 0) > 0:
            await _persist_web_sources(fallback, kwargs)
            return fallback
        return {"error": f"Search failed: {e}"}

    formatted: list[dict[str, str]] = []
    for r in results:
        formatted.append(
            {
                "title": r.get("title", ""),
                "url": r.get("href", r.get("url", "")),
                "snippet": r.get("body", r.get("snippet", "")),
            }
        )

    result = {
        "query": query,
        "results": formatted,
        "count": len(formatted),
    }
    await _persist_web_sources(result, kwargs)
    return result


async def _persist_web_sources(result: dict[str, Any], kwargs: dict[str, Any]) -> None:
    """Persist web search results so the assistant response can cite them."""
    db = kwargs.get("db")
    run_id = kwargs.get("run_id")
    if not db or not run_id:
        return

    for index, item in enumerate(result.get("results", []), start=1):
        url = item.get("url", "")
        if not url:
            continue
        exists = await db.scalar(
            select(WebSource.id).where(WebSource.run_id == run_id, WebSource.url == url)
        )
        if exists is None:
            db.add(
                WebSource(
                    run_id=run_id,
                    url=url,
                    title=item.get("title", ""),
                    excerpt=item.get("snippet", ""),
                    rank=index,
                )
            )
    await db.flush()


async def _web_search_html(query: str, max_results: int) -> dict[str, Any]:
    """Fallback: search DuckDuckGo via HTML scraping (may hit captcha)."""
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, verify=SSL_CERT_PATH
        ) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"Search failed: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, str]] = []

    for block in soup.select(".result"):
        title_el = block.select_one(".result__title a")
        snippet_el = block.select_one(".result__snippet")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
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
            timeout=20, follow_redirects=True, verify=SSL_CERT_PATH
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
