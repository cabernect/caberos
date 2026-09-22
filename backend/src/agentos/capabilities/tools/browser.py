"""Browser capabilities — the agent-facing surface of the Browser module.

Five verbs per the W4 plan: open / observe / act / extract / close.
Observations are bounded semantic projections, never raw HTML; actions
return post-action deltas so one act never costs a redundant observe.
"""

from __future__ import annotations

from typing import Any

from ...browser.cdp import BrowserError
from ...browser.registry import browser_registry

_MAX_EXTRACT_CHARS = 20_000


def _ids(kwargs: dict[str, Any]) -> tuple[str, str | None, str]:
    return kwargs["agent_id"], kwargs.get("session_id"), kwargs["run_id"]


async def browser_open(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, session_id, run_id = _ids(kwargs)
    url = args["url"]
    try:
        _, result = await browser_registry.get_or_open(
            url, agent_id=agent_id, session_id=session_id, run_id=run_id
        )
    except BrowserError as e:
        if str(e).startswith("runtime_unavailable"):
            return {"status": "runtime_unavailable", "detail": str(e)}
        raise
    return {"observation": result}


async def browser_observe(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)
    obs = await session.observe()
    return {"observation": obs.serialize()}


async def browser_act(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)
    delta = await session.act(
        action=args["action"],
        ref=args.get("target", ""),
        value=args.get("value"),
    )
    return {"delta": delta}


async def browser_extract(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)
    data = await session.extract(args["expression"])
    truncated = len(data) > _MAX_EXTRACT_CHARS
    return {
        "data": data[:_MAX_EXTRACT_CHARS],
        **({"truncated": True} if truncated else {}),
    }


async def browser_close(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    _, _, run_id = _ids(kwargs)
    closed = await browser_registry.close_for_run(run_id)
    return {"closed": closed}
