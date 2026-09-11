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

# Extraction libraries — trafilatura for main-content → markdown,
# BeautifulSoup.get_text() as last resort when trafilatura is thin.
try:
    import trafilatura

    _TRAFILATURA_AVAILABLE = True
except ImportError:
    _TRAFILATURA_AVAILABLE = False


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


# Hard context ceiling — system-controlled, not model-overridable.
# The model can request more via offset/has_more, but cannot exceed this.
_WEB_FETCH_HARD_CEILING = 50_000


def _extract_markdown(html: str) -> str:
    """Extract main content as markdown.

    Tries trafilatura first (best boilerplate removal), falls back to
    BeautifulSoup plain text when trafilatura returns thin.
    """
    # trafilatura — best for articles/blogs, removes nav/ads/footers
    if _TRAFILATURA_AVAILABLE:
        text = trafilatura.extract(html, output_format="markdown", include_comments=False)
        if text and len(text) > 100:
            return text

    # Last resort — BeautifulSoup plain text
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    return soup.get_text(separator="\n", strip=True)


async def web_fetch(args: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Fetch a URL and return its text content.

    Args:
        url: The URL to fetch
        max_chars: Maximum characters to return (default: 8000, capped at hard ceiling)
        offset: Character offset to start reading from (default: 0)
    """
    url = args["url"]
    max_chars = args.get("max_chars", 8000)
    offset = args.get("offset", 0)

    # Cap max_chars at the hard ceiling — the model cannot exceed this
    max_chars = min(max_chars, _WEB_FETCH_HARD_CEILING)

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

    # Extract main content as markdown (system-controlled, not a model option)
    text = _extract_markdown(resp.text)

    # Apply offset and max_chars
    content = text[offset : offset + max_chars]
    has_more = (offset + len(content)) < len(text)

    return {
        "url": url,
        "content": content,
        "title": "",
        "offset": offset,
        "has_more": has_more,
        "total_chars": len(text),
    }
