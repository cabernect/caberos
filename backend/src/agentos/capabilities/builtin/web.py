"""Web fetch/search capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.web import web_fetch, web_search


def register() -> None:
    registry.register(
        CapabilityDef(
            name="web_search",
            effects=frozenset({"read"}),
            kind="tool",
            description="Search the web. Returns titles, URLs, and snippets. Uses the "
            "operator-configured search provider (Settings → Tools); falls back to "
            "DuckDuckGo when none is bound. Use this to find current information, "
            "look up documentation, or research topics.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=web_search,
        )
    )

    registry.register(
        CapabilityDef(
            name="web_fetch",
            effects=frozenset({"read"}),
            kind="tool",
            # Static-read contract (v0.2): HTTP retrieval + readable-content
            # extraction only. Never executes JavaScript, never starts the
            # managed browser runtime — dynamic pages are the Browser
            # module's job.
            description="Fetch and extract readable content from a static URL over HTTP. "
            "For HTML pages, removes scripts, styles, and navigation. Does not execute "
            "JavaScript, interact with the page, or start the managed browser runtime. "
            "Use this to read web pages found via web_search.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (capped at 50000)",
                        "default": 8000,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset to start reading from",
                        "default": 0,
                    },
                },
                "required": ["url"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=web_fetch,
        )
    )
