"""Browser capabilities — the agent-facing surface of the Browser module.

Five verbs per the W4 plan: open / observe / act / extract / close.
Observations are bounded semantic projections, never raw HTML; actions
return post-action deltas so one act never costs a redundant observe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...browser.cdp import BrowserError
from ...browser.registry import browser_registry

_MAX_EXTRACT_CHARS = 20_000


def _ids(kwargs: dict[str, Any]) -> tuple[str, str | None, str]:
    return kwargs["agent_id"], kwargs.get("session_id"), kwargs["run_id"]


async def browser_open(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, session_id, run_id = _ids(kwargs)
    url = args["url"]
    research = args.get("mode") == "research"
    ws = kwargs.get("workspace_path")
    staging = Path(ws) / "downloads" if ws else None

    # Scheduled/heartbeat runs must never pop a surprise window (plan:
    # "scheduled work never opens surprise windows"). Refuse honestly —
    # the agent can proceed headless or ask the user via agent_ask_user.
    if args.get("visible") and kwargs.get("trigger", "user_message") != "user_message":
        return {
            "status": "visible_refused",
            "detail": (
                "visible browser sessions require an interactive run — "
                "open headless or ask the user to take over explicitly"
            ),
        }

    allowed: list[str] | None = None
    profile_name = args.get("profile")
    if profile_name:
        import json

        from sqlalchemy import select

        from ...models.browser_profile import BrowserProfile

        row = (
            await kwargs["db"].execute(
                select(BrowserProfile).where(BrowserProfile.name == profile_name)
            )
        ).scalar_one_or_none()
        if row is None:
            return {
                "status": "profile_not_found",
                "detail": (
                    f"no browser profile named '{profile_name}' — the operator creates profiles"
                ),
            }
        allowed = json.loads(row.allowed_domains or "[]") or None

    try:
        _, result = await browser_registry.get_or_open(
            url,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            research=research,
            staging_dir=staging,
            profile=profile_name,
            allowed_domains=allowed,
            visible=bool(args.get("visible")),
        )
    except BrowserError as e:
        if str(e).startswith("runtime_unavailable"):
            return {"status": "runtime_unavailable", "detail": str(e)}
        raise
    return {"observation": result}


async def browser_observe(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)

    if args.get("visual"):
        # On-demand visual observation (plan: screenshots are stored as
        # traceable artifacts, pixels never inline in tool output; the image
        # reaches the model only via _model_content on vision-capable models).
        import base64
        import time
        from pathlib import Path

        png = await session.screenshot()
        shot_dir = Path(kwargs["workspace_path"]) / "artifacts" / "browser"
        shot_dir.mkdir(parents=True, exist_ok=True)
        path = shot_dir / f"shot-{int(time.time())}.png"
        path.write_bytes(png)
        rel = path.relative_to(kwargs["workspace_path"])
        result: dict[str, Any] = {
            "screenshot": str(rel),
            "bytes": len(png),
        }
        if kwargs.get("supports_vision"):
            result["_model_content"] = [
                {"type": "text", "text": f"Page screenshot saved to {rel}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
                },
            ]
        else:
            result["note"] = "saved to workspace; model lacks vision — not sent inline"
        return result

    obs = await session.observe(scope=args.get("scope"))
    out: dict[str, Any] = {"observation": obs.serialize()}
    if session.downloads:
        out["downloads"] = [f"downloads/{d['filename']}" for d in session.downloads]
    if session.blocked_navigations:
        out["blocked_navigations"] = list(session.blocked_navigations)
    return out


async def browser_act(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)
    # Domain-scope widening: an out-of-scope navigation was blocked by the
    # profile's domain policy. Retrying with allow_domain=True widens the
    # session scope — the operator's approval of this call is the decision.
    if args["action"] == "navigate" and args.get("allow_domain"):
        session.allow_domain_for(args.get("value") or "")
    delta = await session.act(
        action=args["action"],
        ref=args.get("target", ""),
        value=args.get("value"),
    )
    out: dict[str, Any] = {"delta": delta}
    if session.blocked_navigations:
        out["blocked_navigations"] = list(session.blocked_navigations)
    return out


async def browser_extract(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    agent_id, _, run_id = _ids(kwargs)
    session = browser_registry.get_owned(run_id, agent_id)
    data = await session.extract(args["expression"])
    ws = kwargs.get("workspace_path")

    # Large extracts are staged as workspace artifacts with a bounded
    # preview — never dumped wholesale into context (plan: extract staging).
    if len(data) > _MAX_EXTRACT_CHARS and ws:
        import time

        out_dir = Path(ws) / "artifacts" / "browser"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"extract-{int(time.time())}.json"
        path.write_text(data)
        return {
            "staged": str(path.relative_to(ws)),
            "bytes": len(data),
            "preview": data[:_MAX_EXTRACT_CHARS],
            "truncated": True,
            "note": "full result written to workspace — read_file for the rest",
        }
    truncated = len(data) > _MAX_EXTRACT_CHARS
    return {
        "data": data[:_MAX_EXTRACT_CHARS],
        **({"truncated": True} if truncated else {}),
    }


async def browser_close(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    _, _, run_id = _ids(kwargs)
    closed = await browser_registry.close_for_run(run_id)
    return {"closed": closed}
