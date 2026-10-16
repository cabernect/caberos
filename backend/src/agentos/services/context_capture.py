"""Model request capture — bounded, redacted record of the SDK boundary.

A capture row records what the model call actually received after request
preparation and redaction — never provider auth material, never raw user
secrets, never a response body. The row's id is the associated ModelCall.id
when one is recorded. Retention expires the body only — metadata, receipts,
and conversation rows are untouched.

Label: captured at CaberOS's SDK boundary after request preparation and
redaction; not a native provider wire capture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, bindparam
from sqlalchemy import text as sqltext

from ..config import settings
from ..models.request_capture import ModelRequestCapture
from ..redaction import (
    NUMERIC_ALLOW_KEYS,
    project_args,
    project_result,
    redact_secrets,
)
from .context_capture_queries import (
    EXPIRE_CAPTURE_AGE,
    EXPIRE_CAPTURE_STORAGE,
    OLDEST_CAPTURE_BODIES,
    RETAINED_CAPTURE_BYTES,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scope — per-async-context metadata supplied by the caller (never a shared
# mutable adapter attribute; concurrent calls must never share a capture).
# ---------------------------------------------------------------------------

_capture_scope: ContextVar[dict | None] = ContextVar("capture_scope", default=None)


@contextmanager
def capture_scope(**fields):
    """Establish capture metadata for one model invocation — run/session/
    agent/subagent/turn/purpose, core revision + identity source, summary
    version, coverage-known flag, source message ids, component budget."""
    token = _capture_scope.set(dict(fields))
    try:
        yield
    finally:
        _capture_scope.reset(token)


def current_capture_scope() -> dict:
    """The live scope dict for the current async context (mutable —
    capture_dispatch writes its reference back here for the caller's
    ledger writer). Public accessor; callers never touch the ContextVar."""
    scope = _capture_scope.get()
    return scope if scope is not None else {}


_SCOPE_KEYS = frozenset(
    {
        "run_id",
        "session_id",
        "agent_id",
        "sub_agent_id",
        "turn",
        "purpose",
        "model",
        "family",
        "core_revision_id",
        "core_identity_source_version_id",
        "summary_version",
        "conversation_summary_id",
        "coverage_known",
        "source_message_ids",
        "source_message_ids_total",
        "source_message_ids_truncated",
        "component_budget",
        "operation",
        "source_core_revision_ids",
        "identity_source_version_id",
    }
)


def _scope() -> dict:
    """Approved scalar/id/count scope fields only — never arbitrary blobs."""
    return project_capture_metadata(current_capture_scope())


def _scrub_text(value: str) -> str:
    from ..harness.memory_prompts import MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN

    clean, _ = redact_secrets(value)
    return re.sub(MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN, "[REDACTED]", clean)


def _safe_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None
        and _scrub_text(value) == value
    )


_BUDGET_COMPONENTS = frozenset(
    {
        "system_prompt",
        "conversation",
        "tools",
        "core",
        "skills",
        "summary",
        "total",
        "input_budget",
        "output_reserve",
    }
)


def _finite_count(value: Any) -> bool:
    """Safe nonnegative bounded numeric check — huge Python ints never go
    through math.isfinite (OverflowError)."""
    if type(value) is bool:
        return False
    if type(value) is int:
        return 0 <= value < 2**63
    if type(value) is float:
        return math.isfinite(value) and 0 <= value < 2**63
    return False


def project_capture_metadata(raw: Any) -> dict:
    """Metadata is references and measured counts, never arbitrary user
    text. Deterministic regardless of frozenset iteration order — the
    ids/count/truncated block is resolved once, after the scalar pass."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    deferred = {
        "source_message_ids",
        "source_message_ids_total",
        "source_message_ids_truncated",
        "source_core_revision_ids",
    }
    for key in _SCOPE_KEYS:
        if key in deferred:
            continue
        value = raw.get(key)
        if value is None:
            continue
        if key == "component_budget" and isinstance(value, dict):
            budget = {
                name: count
                for name, count in value.items()
                if name in _BUDGET_COMPONENTS and _finite_count(count)
            }
            if budget:
                out[key] = budget
        elif key in ("turn", "summary_version"):
            if type(value) is int and value >= 0:
                out[key] = value
        elif key == "coverage_known":
            if type(value) is bool:
                out[key] = value
        elif key == "model":
            if (
                isinstance(value, str)
                and len(value) <= 256
                and "://" not in value
                and _scrub_text(value) == value
            ):
                out[key] = value
        elif _safe_id(value):
            out[key] = value

    # ids + total + truncated — one deterministic final block; a raw
    # nested value can never become a boolean or override the count.
    ids = raw.get("source_message_ids")
    if isinstance(ids, list):
        clean = sorted({item for item in ids if _safe_id(item)})
        supplied_total = raw.get("source_message_ids_total")
        total = len(clean)
        if (
            type(supplied_total) is int
            and not isinstance(supplied_total, bool)
            and supplied_total >= 0
        ):
            total = max(total, supplied_total)
        out["source_message_ids"] = clean[:200]
        out["source_message_ids_total"] = total
        out["source_message_ids_truncated"] = (
            len(clean) > 200 or raw.get("source_message_ids_truncated") is True
        )
    else:
        supplied_total = raw.get("source_message_ids_total")
        if (
            type(supplied_total) is int
            and not isinstance(supplied_total, bool)
            and supplied_total >= 0
        ):
            out["source_message_ids_total"] = supplied_total
            out["source_message_ids_truncated"] = raw.get("source_message_ids_truncated") is True
    revs = raw.get("source_core_revision_ids")
    if isinstance(revs, list):
        out["source_core_revision_ids"] = sorted({item for item in revs if _safe_id(item)})[:200]
    return out


# ---------------------------------------------------------------------------
# Reference + dispatch surfaces
# ---------------------------------------------------------------------------

DISPATCH_ALLOWLIST = frozenset(
    {
        "model",
        "messages",
        "input",
        "instructions",
        "tools",
        "stream",
        "max_tokens",
        "max_output_tokens",
        "temperature",
        "top_p",
        "reasoning",
        "reasoning_effort",
        "thinking",
        "response_format",
        "tool_choice",
        "parallel_tool_calls",
        "stream_options",
    }
)

# Never persisted under any key — auth material only.
_DROP_KEYS = frozenset(
    {
        "api_key",
        "api_base",
        "base_url",
        "organization",
        "headers",
        "extra_headers",
        "aws_access_key_id",
        "aws_secret_access_key",
        "authorization",
    }
)

# Sensitive capability names whose args/results go through the per-capability
# projectors (browser creds, HITL answers, memory content) — the same policy
# the observability surface already uses.
_SENSITIVE_PREFIXES = ("browser_", "artifact_", "memory_", "doc_")
_SENSITIVE_NAMES = {
    "read_file",
    "terminal",
    "read_terminal",
    "close_terminal",
    "agent_ask_user",
    "run_subagent",
    "write_file",
    "web_fetch",
}


@dataclass(frozen=True)
class CaptureReference:
    """What the transport actually saw — a safe reference, not the payload."""

    id: str | None
    state: str  # available/partial/failed/expired/not_recorded/not_applicable
    reason: str | None = None
    redacted: bool = False
    truncated: bool = False
    surface: str | None = None
    latency_ms: int | None = None
    attempt_metadata: dict | None = None


# Global in-process serialization for capture writes + pruning — independent
# of any caller transaction; never blocks a model call on another writer.
_write_lock = asyncio.Lock()

_SECRETISH_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|auth|credential|cookie|"
    r"private[_-]?key|client[_-]?secret)"
)

_MEDIA_TYPES = frozenset(
    {
        "image_url",
        "input_image",
        "image",
        "file",
        "input_file",
        "audio",
        "video",
        "input_audio",
        "input_video",
        "audio_url",
        "video_url",
    }
)


def _is_sensitive_name(name: str) -> bool:
    return name in _SENSITIVE_NAMES or name.startswith(_SENSITIVE_PREFIXES)


def _scrub_value(value: Any, cap_name: str | None, *, depth: int = 0, flags: dict) -> Any:
    """Recursive structured scrub — secret-named keys dropped (NO value
    exemption for credentials; numeric values survive only under the exact
    NUMERIC_ALLOW_KEYS control names), strings secret-redacted, JSON-looking
    strings parsed and scrubbed recursively, images/binary marked omitted,
    malformed objects fail closed."""
    if depth > 16:
        flags["truncated"] = True
        return {"_depth": "max"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        flags["redacted"] = True
        flags["truncated"] = True
        return {"_omitted": "binary data", "bytes": len(value)}
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value[:128]:
            flags.update(redacted=True, truncated=True)
            return {"_omitted": "inline media"}
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if parsed is not None:
                projected = _scrub_value(parsed, cap_name, depth=depth + 1, flags=flags)
                return json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        red = _scrub_text(value)
        flags["redacted"] = flags.get("redacted", False) or red != value
        return red
    if isinstance(value, list):
        if len(value) > 10000:
            flags["truncated"] = True
        return [_scrub_value(v, cap_name, depth=depth + 1, flags=flags) for v in value[:10000]]
    if isinstance(value, dict):
        # A content-part dict typed as media is omitted wholesale — images,
        # files, and base64 payloads never persist.
        if value.get("type") in _MEDIA_TYPES:
            flags["redacted"] = True
            flags["truncated"] = True
            return {"_omitted": value.get("type"), "media": True}
        out = {}
        for k, v in value.items():
            k_str = str(k)
            if k_str in {
                "base64",
                "b64_json",
                "file_data",
                "image_data",
                "image_base64",
                "audio_data",
            }:
                flags.update(redacted=True, truncated=True)
                out[k_str] = {"_omitted": "binary data"}
                continue
            if k_str.lower() in _DROP_KEYS or _SECRETISH_KEY_RE.search(k_str):
                # Secret-named keys: no value of any type persists. Only an
                # exact known numeric control key keeps its number.
                if (
                    k_str in NUMERIC_ALLOW_KEYS
                    and isinstance(v, (int, float))
                    and not isinstance(v, bool)
                ):
                    out[k_str] = v
                else:
                    flags["redacted"] = True
                    out[k_str] = {"_redacted": True}
                continue
            out[k_str] = _scrub_value(v, cap_name, depth=depth + 1, flags=flags)
        return out
    flags["redacted"] = True
    return {"_unserializable": True}


def _scrub_args(name: str, raw: Any, flags: dict) -> Any:
    """One capability's arguments — parsed then either per-capability
    projected (sensitive names/prefixes) or generically scrubbed."""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        parsed = raw
    if _is_sensitive_name(name):
        projected, _red, _tr = project_args(name, parsed)
        flags["redacted"] = True
        flags["truncated"] = flags.get("truncated", False) or _tr
        return _scrub_value(projected, name, depth=2, flags=flags)
    return _scrub_value(parsed, name, depth=2, flags=flags)


def _scrub_message(msg: Any, flags: dict, call_id_to_name: dict, aliases: dict[str, str]) -> Any:
    """One message — every field scrubbed; tool_call / function_call
    arguments parsed + projected; sensitive tool RESULT bodies keyed back
    to their original capability name."""
    if not isinstance(msg, dict):
        return _scrub_value(msg, None, flags=flags)

    msg_type = msg.get("type")
    out: dict[str, Any] = {}
    for k, v in msg.items():
        if k == "tool_calls" and isinstance(v, list):
            new_calls = []
            for call in v:
                if not isinstance(call, dict):
                    new_calls.append(_scrub_value(call, None, flags=flags))
                    continue
                c = dict(call)
                fn = c.get("function") or {}
                native_name = fn.get("name") or c.get("name") or ""
                name = aliases.get(native_name, native_name)
                if c.get("id") and name:
                    call_id_to_name[c["id"]] = name
                if fn.get("arguments") is not None:
                    c = _scrub_value(
                        {key: item for key, item in c.items() if key != "function"},
                        None,
                        depth=2,
                        flags=flags,
                    )
                    c["function"] = {
                        **_scrub_value(
                            {key: item for key, item in fn.items() if key != "arguments"},
                            None,
                            depth=2,
                            flags=flags,
                        ),
                        "arguments": _scrub_args(name, fn["arguments"], flags),
                    }
                    new_calls.append(c)
                else:
                    new_calls.append(_scrub_value(c, name, flags=flags))
            out[k] = new_calls
        elif msg_type == "function_call" and k == "arguments":
            native_name = str(msg.get("name") or "")
            out[k] = _scrub_args(aliases.get(native_name, native_name), v, flags)
        elif msg_type == "function_call" and k == "call_id" and msg.get("name"):
            call_id_to_name[v] = aliases.get(str(msg["name"]), str(msg["name"]))
            out[k] = v
        else:
            out[k] = _scrub_value(v, None, depth=2, flags=flags)
    return out


def _scrub_messages(msgs: list, flags: dict, aliases: dict | None = None) -> list:
    if len(msgs) > 10000:
        flags["truncated"] = True
    call_id_to_name: dict[str, str] = {}
    out = [_scrub_message(m, flags, call_id_to_name, aliases or {}) for m in msgs[:10000]]
    # Second pass — sensitive tool-result bodies projected by capability.
    for i, msg in enumerate(out):
        if not isinstance(msg, dict):
            continue
        m = dict(msg)
        cid = m.get("tool_call_id")
        if cid is None and m.get("type") == "function_call_output":
            cid = m.get("call_id") or m.get("id")
        cap = call_id_to_name.get(cid) if cid else None
        if cap and _is_sensitive_name(cap) and m.get("content") is not None:
            projected, _r, _t = project_result(cap, m["content"])
            flags["redacted"] = True
            flags["truncated"] = flags.get("truncated", False) or _t
            m["content"] = _scrub_value(projected, cap, flags=flags)
        elif cap and _is_sensitive_name(cap) and m.get("output") is not None:
            projected, _r, _t = project_result(cap, m["output"])
            flags["redacted"] = True
            flags["truncated"] = flags.get("truncated", False) or _t
            m["output"] = _scrub_value(projected, cap, flags=flags)
        out[i] = m
    return out


def _scrub_tool_schemas(tools: list, flags: dict) -> list:
    """Schema property names/definitions preserved; secret-named parameter
    DEFAULTS/examples/enum values stripped — the name itself stays."""
    return _scrub_schema(tools, flags)


def _scrub_schema(value: Any, flags: dict, *, sensitive: bool = False, depth: int = 0) -> Any:
    if depth > 16:
        flags["truncated"] = True
        return {"_omitted": "schema depth"}
    if isinstance(value, list):
        flags["truncated"] = flags.get("truncated", False) or len(value) > 10000
        return [
            _scrub_schema(item, flags, sensitive=sensitive, depth=depth + 1)
            for item in value[:10000]
        ]
    if not isinstance(value, dict):
        return _scrub_value(value, None, flags=flags)
    out = {}
    for key, item in value.items():
        if sensitive and key in ("default", "example", "examples", "enum", "const"):
            flags["redacted"] = True
            continue
        if _SECRETISH_KEY_RE.search(key):
            flags["redacted"] = True
            out[key] = {"_redacted": True}
            continue
        if key in ("properties", "patternProperties", "$defs", "definitions"):
            if not isinstance(item, dict):
                flags["truncated"] = True
                out[key] = {"_omitted": "invalid schema"}
                continue
            out[key] = {
                name: _scrub_schema(
                    definition,
                    flags,
                    sensitive=bool(_SECRETISH_KEY_RE.search(name)),
                    depth=depth + 1,
                )
                for name, definition in item.items()
            }
        else:
            out[key] = _scrub_schema(item, flags, sensitive=sensitive, depth=depth + 1)
    return out


def _freeze_body(
    surface: str,
    kwargs: dict[str, Any],
    rendered: dict | None = None,
    tool_aliases: dict[str, str] | None = None,
) -> tuple[dict, dict, dict]:
    """Deep-project dispatch kwargs into a bounded capture body.
    `rendered` = caller-rendered messages/tools BEFORE SDK normalization —
    canonical names; dispatch_input is the allowlisted final SDK input."""
    flags: dict[str, bool] = {"redacted": False, "truncated": False}

    dispatch_input: dict[str, Any] = {}
    extras: list[str] = []
    for key, value in kwargs.items():
        if key.lower() in _DROP_KEYS:
            continue
        if key not in DISPATCH_ALLOWLIST:
            extras.append(key)
            continue
        if key in ("messages", "input") and isinstance(value, list):
            dispatch_input[key] = _scrub_messages(value, flags, tool_aliases)
        elif key == "tools" and isinstance(value, list):
            dispatch_input[key] = _scrub_tool_schemas(value, flags)
        else:
            dispatch_input[key] = _scrub_value(value, None, depth=2, flags=flags)

    if rendered and (rendered.get("messages") or rendered.get("tools")):
        rendered_ctx = {
            "messages": _scrub_messages(rendered.get("messages") or [], flags),
            "tools": _scrub_tool_schemas(rendered.get("tools") or [], flags),
        }
    else:
        rendered_ctx = {
            "messages": dispatch_input.get("messages") or dispatch_input.get("input") or [],
            "tools": dispatch_input.get("tools") or [],
        }

    payload = {
        "rendered_context": rendered_ctx,
        "dispatch_input": dispatch_input,
    }
    if extras:
        flags["truncated"] = True
    meta = {
        "surface": surface,
        # Extras are metadata — a count + flag, never raw provider-extra
        # key names (a hostile extra name could itself leak a secret).
        "omitted_extras": {"count": len(extras)} if extras else {"count": 0},
        "boundary_label": (
            "Captured at CaberOS's SDK boundary after request preparation "
            "and redaction; not a native provider wire capture."
        ),
    }
    return payload, meta, flags


async def _retained_bytes(session: Any) -> int:
    return int((await session.execute(sqltext(RETAINED_CAPTURE_BYTES))).scalar() or 0)


def _serialize_body(
    payload: dict, meta: dict, effective: int
) -> tuple[str | None, int, bool, str | None]:
    """Serialize valid UTF-8 JSON within the effective byte cap — halving
    of string allowances and list bounds keeps the JSON valid or the body
    drops with a specific reason."""
    previous_size = None
    truncated = False
    while True:
        try:
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        except (ValueError, TypeError):
            return None, 0, False, "unserializable"
        size = len(text.encode("utf-8"))
        if size <= effective:
            return text, size, truncated, None
        if previous_size is not None and size >= previous_size:
            return None, 0, True, "payload_over_limit"
        previous_size = size
        payload = _halve_payload(payload)
        truncated = True


def _halve_payload(value: Any, depth: int = 0) -> Any:
    """Halve strings AND lists — keeps valid JSON and actually shrinks."""
    if depth > 16:
        return value
    if isinstance(value, str) and len(value) > 64:
        return value[: len(value) // 2] + "…"
    if isinstance(value, list):
        kept = value[: max(1, len(value) // 2)]
        return [_halve_payload(v, depth + 1) for v in kept]
    if isinstance(value, dict):
        return {k: _halve_payload(v, depth + 1) for k, v in value.items()}
    return value


async def _persist_capture(
    session: Any,
    capture_id: str,
    payload_text: str | None,
    payload_bytes: int,
    state: str,
    meta: dict,
) -> None:
    """Insert + retention prune inside the caller's write-lock-held
    transaction — one commit for the whole unit."""
    now = datetime.now(UTC)
    session.add(
        ModelRequestCapture(
            id=capture_id,
            payload=payload_text,
            payload_bytes=payload_bytes,
            state=state,
            capture_meta=json.dumps(meta, default=str),
            created_at=now,
        )
    )
    await session.flush()
    await _enforce_retention(session)


async def enforce_retention() -> None:
    """Public inspection-time retention — its own short transaction so aged
    bodies don't survive merely because no new model call has run."""
    from ..db import async_session_factory

    async with _write_lock:
        async with async_session_factory() as owned:
            await _enforce_retention(owned)
            await owned.commit()


async def _enforce_retention(session: Any) -> None:
    """Age expiry first, then oldest-first storage cap — bodies only.
    Does NOT commit — the caller owns the transaction boundary."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.context_capture_retention_days)
    # Typed DateTime bindparams — Postgres binds TIMESTAMPTZ; SQLite stores
    # naive space-separated timestamps so bound values drop tz there.
    bound = {"now": now, "cutoff": cutoff}
    age_q = sqltext(EXPIRE_CAPTURE_AGE).bindparams(
        bindparam("now", type_=DateTime(timezone=True)),
        bindparam("cutoff", type_=DateTime(timezone=True)),
    )
    await session.execute(age_q, bound)
    retained = (await session.execute(sqltext(RETAINED_CAPTURE_BYTES))).scalar() or 0
    if retained <= settings.context_capture_max_bytes:
        return
    expire_q = sqltext(EXPIRE_CAPTURE_STORAGE).bindparams(
        bindparam("now", type_=DateTime(timezone=True)),
    )
    now_bound = bound["now"]
    rows = (await session.execute(sqltext(OLDEST_CAPTURE_BODIES))).fetchall()
    for cid, size in rows:
        if retained <= settings.context_capture_max_bytes:
            break
        await session.execute(expire_q, {"capture_id": cid, "now": now_bound})
        retained -= size or 0


async def capture_dispatch(
    surface: str,
    kwargs: dict[str, Any],
    call_fn: Any,
    *,
    rendered: dict | None = None,
    tool_aliases: dict[str, str] | None = None,
    attempt_metadata: dict | None = None,
) -> tuple[Any, CaptureReference]:
    """Freeze + redact + persist the dispatch body, then call `call_fn` on
    the ORIGINAL unmodified kwargs. `rendered` is the caller-rendered
    messages/tools BEFORE SDK normalization.

    Capture is best-effort: a redactor, sizing, or persistence failure can
    never block the SDK call — the reference records the failed state.
    The returned async-iterator result is wrapped so stream-consumption
    errors keep this same reference."""
    scope_dict = current_capture_scope()
    capture_id = str(uuid.uuid4())
    state = "available"
    reason = None
    flags: dict = {"redacted": False, "truncated": False}

    payload_text: str | None = None
    payload_bytes = 0
    scope: dict = {}
    meta: dict = {"surface": surface, "scope": scope}

    try:
        scope = _scope()
        payload, meta, flags = _freeze_body(
            surface, kwargs, rendered=rendered, tool_aliases=tool_aliases
        )
        meta["scope"] = scope
        effective = min(
            settings.context_capture_max_payload_bytes, settings.context_capture_max_bytes
        )
        payload_text, payload_bytes, partial, fail_reason = _serialize_body(
            payload, meta, effective
        )
        flags["truncated"] = flags.get("truncated", False) or partial
        if payload_text is None:
            # Unserializable/projection failure — never claim a body that
            # does not exist.
            state, reason = "failed", fail_reason or "unserializable"
        elif flags["truncated"]:
            state, reason = "partial", fail_reason or "projected_or_over_limit"
        meta["flags"] = dict(flags)
        meta["reason"] = reason
    except Exception:
        state, reason = "failed", "capture_error"
        payload_text, payload_bytes = None, 0
        meta = {"surface": surface, "scope": scope, "reason": reason}
        log.warning("context capture projection failed")
    try:
        from ..db import async_session_factory

        async with _write_lock:
            async with async_session_factory() as session:
                await _persist_capture(
                    session, capture_id, payload_text, payload_bytes, state, meta
                )
                await session.commit()
    except Exception:
        state, reason = "failed", "save_failed"
        log.warning("context capture save failed")

    try:
        safe_attempt = {
            **scope,
            **{
                key: value
                for key, value in (attempt_metadata or {}).items()
                if key in ("provider_id", "model_name", "model_str")
                and isinstance(value, str)
                and _scrub_text(value) == value
                and len(value) <= 256
                and "://" not in value
            },
        }
    except Exception:
        safe_attempt = dict(scope)
    ref = CaptureReference(
        id=capture_id,
        state=state,
        reason=reason,
        redacted=flags.get("redacted", False),
        truncated=flags.get("truncated", False),
        surface=surface,
        attempt_metadata=safe_attempt,
    )
    # The scope carries the ref back to the caller's ledger writer; an
    # exception also carries it so a rejected attempt keeps its capture.
    scope_dict["capture_ref"] = ref
    started = time.monotonic()
    try:
        result = await call_fn(**kwargs)
    except BaseException as exc:
        ref = dc_replace(ref, latency_ms=int((time.monotonic() - started) * 1000))
        try:
            exc.capture_ref = ref  # type: ignore[attr-defined]
        except Exception:
            pass
        # A rejected attempt is still a ledger event — record the failed
        # receipt under the same capture id; the caller's final writer
        # upserts on that id (one receipt per attempt, never duplicates).
        await record_dispatch_failure(ref, exc)
        raise

    ref = dc_replace(ref, latency_ms=int((time.monotonic() - started) * 1000))
    if hasattr(result, "__aiter__"):
        return _wrap_stream(result, ref, started), ref
    return result, ref


async def record_dispatch_failure(ref: CaptureReference, exc: BaseException) -> None:
    """Persist a failed ModelCall receipt for a rejected dispatch attempt —
    scope supplies run/turn/agent; upserts on the capture id so a caller's
    final writer never duplicates the receipt."""
    from ..db import async_session_factory, retry_locked_transaction
    from ..models.model_call import ModelCall
    from ..redaction import redact_secrets

    try:
        status = "timeout" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "error"
        # Generic exception TYPE only — provider error bodies can echo
        # private request content and never enter the receipt.
        err_text, _ = redact_secrets(f"{type(exc).__name__}")
        err_text = err_text[:2000]
        detail = {
            "capture_id": ref.id,
            "capture_state": ref.state,
            "capture_surface": ref.surface,
        }
        async with async_session_factory() as session:

            async def _write() -> None:
                row = await session.get(ModelCall, ref.id)
                if row is None:
                    row = ModelCall(
                        id=ref.id,
                        run_id=scope_run_id(ref),
                        agent_id=scope_agent_id(ref),
                        sub_agent_id=scope_sub_agent_id(ref),
                        turn=scope_turn(ref),
                        kind="chat",
                        purpose=scope_purpose(ref),
                        provider_id=_attempt_field(ref, "provider_id"),
                        model_name=_attempt_field(ref, "model_name"),
                        model_str=_attempt_field(ref, "model_str"),
                        streamed=bool((ref.surface or "").endswith("stream")),
                        latency_ms=ref.latency_ms,
                        status=status,
                        error=err_text,
                        detail=detail,
                    )
                    session.add(row)
                else:
                    row.status = status
                    row.error = err_text
                    row.detail = {**(row.detail or {}), **detail}
                await session.commit()

            await retry_locked_transaction(_write, session, f"capture_fail:{ref.id}")
    except Exception:
        log.warning("failed-attempt receipt write failed")


def _attempt_field(ref: CaptureReference, key: str) -> Any:
    return (ref.attempt_metadata or {}).get(key)


def scope_run_id(ref: CaptureReference) -> str | None:
    v = _attempt_field(ref, "run_id")
    return v if isinstance(v, str) else None


def scope_agent_id(ref: CaptureReference) -> str | None:
    v = _attempt_field(ref, "agent_id")
    return v if isinstance(v, str) else None


def scope_sub_agent_id(ref: CaptureReference) -> str | None:
    v = _attempt_field(ref, "sub_agent_id")
    return v if isinstance(v, str) else None


def scope_turn(ref: CaptureReference) -> int:
    v = _attempt_field(ref, "turn")
    return v if type(v) is int else 0


def scope_purpose(ref: CaptureReference) -> str:
    v = _attempt_field(ref, "purpose")
    return v if isinstance(v, str) else "reasoning"


class _StreamCapture:
    """AsyncIterator wrapper over a live model stream — exposes
    `request_capture` as the CURRENT attempt reference: on stream end or
    failure the reference is replaced with the whole-attempt duration,
    never the iterator-creation timestamp. Errors attach the latest ref
    and record the failed receipt."""

    def __init__(self, stream: Any, ref: CaptureReference, started: float):
        # Normalize to an iterator — the dispatch seam accepts any async
        # iterable; only iterators guarantee __anext__.
        self._stream = aiter(stream)
        self._ref = ref
        self._started = started

    @property
    def request_capture(self) -> CaptureReference:
        return self._ref

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self._stream.__anext__()
        except StopAsyncIteration:
            self._ref = dc_replace(
                self._ref,
                latency_ms=int((time.monotonic() - self._started) * 1000),
            )
            raise
        except BaseException as exc:
            self._ref = dc_replace(
                self._ref,
                latency_ms=int((time.monotonic() - self._started) * 1000),
            )
            try:
                exc.capture_ref = self._ref  # type: ignore[attr-defined]
            except Exception:
                pass
            await record_dispatch_failure(self._ref, exc)
            raise


def _wrap_stream(stream: Any, ref: CaptureReference, started: float) -> Any:
    return _StreamCapture(stream, ref, started)


# ---------------------------------------------------------------------------
# Read-side projection — a stored body is scrubbed AGAIN at inspection so a
# legacy write can never serve raw credential canaries to the operator.
# ---------------------------------------------------------------------------

_SURFACE_NAMES = frozenset({"chat", "chat_stream", "responses", "responses_stream"})
_REASON_CODES = frozenset(
    {
        "age_limit",
        "storage_limit",
        "storage_limit_reached",
        "payload_over_limit",
        "projected_or_over_limit",
        "over_limit",
        "unserializable",
        "malformed_body",
        "capture_error",
        "save_failed",
        "no_body",
        "malformed_metadata",
    }
)
BOUNDARY_LABEL = (
    "Captured at CaberOS's SDK boundary after request preparation "
    "and redaction; not a native provider wire capture."
)


def project_capture_payload(stored: Any) -> tuple[dict | None, dict]:
    """Re-project a stored capture body through the same structured
    scrubbers used at write time — capability-sensitive args/results and
    secret-shaped keys die again here, while ordinary content, schema
    property names, and types pass through. Returns (payload, flags)."""
    flags: dict = {"redacted": False, "truncated": False}
    if not isinstance(stored, dict):
        return None, flags
    out: dict[str, Any] = {}
    dispatch = stored.get("dispatch_input")
    if isinstance(dispatch, dict):
        projected: dict[str, Any] = {}
        for key, value in dispatch.items():
            if key not in DISPATCH_ALLOWLIST:
                flags["truncated"] = True
                continue
            if key in ("messages", "input") and isinstance(value, list):
                projected[key] = _scrub_messages(value, flags)
            elif key == "tools" and isinstance(value, list):
                projected[key] = _scrub_tool_schemas(value, flags)
            else:
                projected[key] = _scrub_value(value, None, depth=0, flags=flags)
        out["dispatch_input"] = projected
    rendered = stored.get("rendered_context")
    if isinstance(rendered, dict):
        projected_rendered: dict[str, Any] = {}
        if isinstance(rendered.get("messages"), list):
            projected_rendered["messages"] = _scrub_messages(rendered["messages"], flags)
        if isinstance(rendered.get("tools"), list):
            projected_rendered["tools"] = _scrub_tool_schemas(rendered["tools"], flags)
        out["rendered_context"] = projected_rendered
    return (out or None), flags


def allowed_surface(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in _SURFACE_NAMES else None


def allowed_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in _REASON_CODES else None
