"""Bounded search-service dispatch; credentials reuse the Provider store."""

import asyncio
import json
import math
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..models.provider import Provider
from ..secret_store import decrypt
from ..ssl_utils import SSL_CERT_PATH
from .search_endpoints import SELF_HOSTED, pinned_self_hosted_url
from .service_types import SEARCH_PROVIDER_LABELS

MAX_RESPONSE_BYTES = 512 * 1024


def _request(
    service: str, query: str, limit: int, key: str, options: dict[str, Any]
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    request: dict[str, Any] = {"method": "POST", "headers": headers}
    if service == "tavily":
        headers["Authorization"] = f"Bearer {key}"
        request.update(
            url="https://api.tavily.com/search",
            json={
                "query": query,
                "max_results": limit,
                "search_depth": options.get("search_depth", "basic"),
                "include_answer": False,
                "include_raw_content": False,
                "include_usage": True,
            },
        )
    elif service == "exa":
        headers["x-api-key"] = key
        request.update(
            url="https://api.exa.ai/search",
            json={
                "query": query,
                "numResults": limit,
                "type": options.get("exa_search_type", "auto"),
                "contents": {"text": False, "highlights": {"maxCharacters": 2000}},
            },
        )
    elif service == "brave_search":
        headers["X-Subscription-Token"] = key
        request.update(
            method="GET",
            url="https://api.search.brave.com/res/v1/web/search",
            params={
                "q": query,
                "count": limit,
                "safesearch": options.get("brave_safesearch", "moderate"),
                "result_filter": "web",
                "text_decorations": "false",
                "summary": "false",
            },
        )
    else:
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request.update(
            url="https://api.firecrawl.dev/v2/search",
            json={
                "query": query,
                "limit": limit,
                "sources": [{"type": "web"}],
                "timeout": 20000,
            },
        )
    return request


def _results(service: str, payload: dict[str, Any], limit: int) -> list[dict[str, str]]:
    hits = payload.get("results")
    if service == "brave_search":
        web = payload.get("web")
        # Brave omits the web section when there are no results.
        hits = web.get("results", []) if isinstance(web, dict) else [] if web is None else None
    elif service in {"firecrawl", SELF_HOSTED}:
        if payload.get("success") is not True:
            raise ValueError("search rejected")
        data = payload.get("data")
        hits = data.get("web") if isinstance(data, dict) else data
    if not isinstance(hits, list):
        raise ValueError("invalid results")
    results = []
    for hit in hits[:limit]:
        if not isinstance(hit, dict):
            raise ValueError("invalid result")
        url, title = hit.get("url"), hit.get("title") or ""
        if not isinstance(url, str) or len(url) > 4096:
            continue
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            continue
        snippet = hit.get("content") if service == "tavily" else hit.get("description")
        if service == "exa":
            highlights = hit.get("highlights") or []
            if not isinstance(highlights, list) or any(not isinstance(x, str) for x in highlights):
                raise ValueError("invalid highlights")
            snippet = " ".join(highlights[:3])
        snippet = snippet or ""
        if not isinstance(title, str) or not isinstance(snippet, str):
            raise ValueError("invalid result text")
        results.append({"title": title[:1000], "url": url, "snippet": snippet[:4000]})
    return results


def _nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
        and value >= 0
    )


async def search_provider(
    provider: Provider,
    query: str,
    max_results: int = 5,
    *,
    search_depth: str = "basic",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One attempt, fixed destination, no retry, answer generation, or URL fetch."""
    service = provider.type
    if service not in SEARCH_PROVIDER_LABELS:
        return {"error": "This search service is not implemented."}
    label = SEARCH_PROVIDER_LABELS[service]
    query_limit = (
        500 if service in {"firecrawl", SELF_HOSTED} else 600 if service == "brave_search" else 2000
    )
    if not isinstance(query, str) or not query.strip() or len(query) > query_limit:
        return {"error": f"{label} query must contain 1 to {query_limit} characters."}
    if service == "brave_search" and len(query.split()) > 75:
        return {"error": "Brave Search API accepts at most 75 query words."}
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= 10
    ):
        return {"error": "max_results must be between 1 and 10."}
    options = options if options is not None else {"search_depth": search_depth}
    if options.get("search_depth", "basic") not in ("basic", "advanced"):
        return {"error": "Unsupported search depth."}
    if options.get("exa_search_type", "auto") not in ("auto", "fast"):
        return {"error": "Unsupported Exa search type."}
    if options.get("brave_safesearch", "moderate") not in ("off", "moderate", "strict"):
        return {"error": "Unsupported Brave SafeSearch setting."}
    if not provider.encrypted_key and service != SELF_HOSTED:
        return {"error": "Search provider has no API key."}
    try:
        api_key = decrypt(provider.encrypted_key) if provider.encrypted_key else ""
    except Exception:
        return {"error": "Search provider credentials could not be read. Replace the API key."}

    started = time.monotonic()
    receipt: dict[str, Any] = {
        "provider_id": provider.id,
        "service": provider.type,
        "requests": 0,
        "request_units_source": "measured",
        "credits": None,
        "cost": None,
        "cost_status": "unknown",
        "status": "error",
    }
    try:
        async with asyncio.timeout(30):
            request = _request(service, query, max_results, api_key, options)
            if service == SELF_HOSTED:
                url, host_headers, extensions = await pinned_self_hosted_url(
                    provider.base_url or "", json.loads(provider.extra_params or "{}")
                )
                request.update(url=url, extensions=extensions)
                request["headers"].update(host_headers)
            async with httpx.AsyncClient(
                verify=SSL_CERT_PATH, timeout=20, follow_redirects=False, trust_env=False
            ) as client:
                receipt["requests"] = 1
                async with client.stream(**request) as response:
                    # Never surface provider bodies or exception strings: they
                    # may contain echoed credentials or private request content.
                    if response.status_code != 200:
                        return {
                            "error": f"{label} search failed (HTTP {response.status_code}).",
                            "service_usage": receipt,
                        }
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        chunks.extend(chunk)
                        if len(chunks) > MAX_RESPONSE_BYTES:
                            raise ValueError("oversized response")
        payload = json.loads(chunks)
        if not isinstance(payload, dict):
            raise ValueError("invalid search response")
        results = _results(service, payload, max_results)
        usage = payload.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        if service in {"firecrawl", SELF_HOSTED}:
            credits = payload.get("creditsUsed")
        if _nonnegative_number(credits):
            receipt["credits"] = credits
            receipt["credits_source"] = "reported"
        estimate = payload.get("costDollars")
        estimate = estimate.get("total") if isinstance(estimate, dict) else None
        if service == "exa" and _nonnegative_number(estimate):
            receipt.update(
                estimated_cost=estimate,
                estimated_cost_source="provider",
                currency="USD",
                cost_status="estimated",
            )
        receipt["status"] = "ok"
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "service_usage": receipt,
        }
    except (TimeoutError, httpx.TimeoutException):
        receipt["status"] = "timeout"
        return {
            "error": f"{label} search timed out; it may have incurred a charge.",
            "service_usage": receipt,
        }
    except (httpx.HTTPError, ValueError, OSError):
        message = (
            "Self-hosted Firecrawl is blocked or unreachable; "
            "check the server URL and network consent."
            if service == SELF_HOSTED and not receipt["requests"]
            else f"{label} search failed or returned invalid data."
        )
        return {"error": message, "service_usage": receipt}
    finally:
        receipt["latency_ms"] = int((time.monotonic() - started) * 1000)
