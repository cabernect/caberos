"""Shared secret redaction — the single home for the regex patterns, the
redact helper used by harness guardrails, and the read-boundary payload
sanitizer behind the observability API (audit args/results, messages,
timeline events, model-call detail).

Read-boundary contract:
- Structure is preserved: projected payloads stay dict/list/scalars —
  never raw-cut JSON text (a cut could leave a secret fragment).
- Secrets are scrubbed BEFORE bounding, so a truncation boundary can
  never expose part of a key.
- Keys that carry secrets are dropped recursively — even short canaries
  in nested fields like {"cookies": {"s": "x"}}.
- Anything a projector can't positively classify fails closed (omitted),
  never passes through raw.
"""

import json
import re
from urllib.parse import urlsplit, urlunsplit

# Patterns for common secret formats. Each is (name, regex, group_to_redact).
SECRET_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    # OpenAI API keys: sk-proj-... or sk-... (40+ chars)
    (
        "OpenAI API key",
        re.compile(r"(sk-proj-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{40,})"),
        1,
    ),
    # Anthropic API keys: sk-ant-...
    (
        "Anthropic API key",
        re.compile(r"(sk-ant-[A-Za-z0-9_\-]{40,})"),
        1,
    ),
    # GitHub tokens: ghp_..., gho_..., ghs_..., ghu_...
    (
        "GitHub token",
        re.compile(r"(gh[pousr]_[A-Za-z0-9]{36,})"),
        1,
    ),
    # Google API keys: AIza...
    (
        "Google API key",
        re.compile(r"(AIza[A-Za-z0-9_\-]{35})"),
        1,
    ),
    # Generic Bearer tokens (in case a full Authorization header is echoed)
    (
        "Bearer token",
        re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.=]{20,})"),
        1,
    ),
    # Generic high-entropy strings labeled as keys/passwords/secrets
    # Matches: api_key=..., password=..., secret=..., token=...
    (
        "Labeled secret",
        re.compile(
            r"""(?i)((?:api[_-]?key|password|passwd|secret|token|access[_-]?key)\s*[=:]\s*["']?[A-Za-z0-9_\-]{16,}["']?)"""
        ),
        1,
    ),
    # AWS access keys
    (
        "AWS access key",
        re.compile(r"(AKIA[A-Z0-9]{16})"),
        1,
    ),
]


def redact_secrets(content: str) -> tuple[str, list[str]]:
    """Scan for secrets and redact them. Returns (redacted_content, descriptions)."""
    redactions: list[str] = []
    for name, pattern, group in SECRET_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            redacted_count = len(matches)
            # Sanitize: don't log the actual secret, just the name + count
            redactions.append(f"{name} ({redacted_count} occurrence(s))")
            content = pattern.sub(
                lambda m: m.group(group).replace(m.group(group), "[REDACTED]"), content
            )
    return content, redactions


def redact_text(content: str | None, max_chars: int | None = None) -> tuple[str | None, bool, bool]:
    """Redact secrets then bound the string.

    Returns (text, redacted, truncated). Secrets are scrubbed first so a
    truncated boundary can never expose a fragment of a secret.
    """
    if content is None:
        return None, False, False
    text, redactions = redact_secrets(content)
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return text, bool(redactions), truncated


# ---------------------------------------------------------------------------
# Structural sanitizer
# ---------------------------------------------------------------------------

# JSON keys that always carry secrets — dropped recursively regardless of
# nesting depth. Deliberately generous: at the read boundary a false
# positive loses metadata, a false negative leaks a credential.
SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|apikey|secret|token|bearer|authorization|"
    r"cookie|cookies|storage|header|headers|credential|credentials|env|"
    r"session|signature|private[_-]?key|access[_-]?key|auth|oauth)"
)

# Keys that are never part of any projected payload — transport-only
# fields, internal scratch, provider-native content.
PROHIBITED_KEYS = {"_model_content"}

# The ONLY secret-regex-named keys allowed to keep numeric values —
# token counters aren't credentials. Everything else under a secret
# name drops regardless of type.
NUMERIC_ALLOW_KEYS = frozenset(
    {
        "tokens_in",
        "tokens_out",
        "thinking_tokens",
        "cached_tokens",
        "context_tokens",
        "max_context_tokens",
        "total_tokens_in",
        "total_tokens_out",
    }
)


def _secret_key(key) -> bool:
    return SECRET_KEY_RE.search(str(key)) is not None or str(key) in PROHIBITED_KEYS


def _scrub(value, max_depth: int, max_list: int, max_str: int, depth: int = 0):
    """Recursive scrub → (value, redacted, truncated).

    Containers deeper than max_depth collapse to a marker; lists keep
    max_list items; strings redact then bound to max_str. Scalars are
    kept at any depth (they can't hide structure).
    """
    if isinstance(value, dict):
        if depth >= max_depth:
            return "…", False, True
        out = {}
        redacted = False
        truncated = False
        for i, (k, v) in enumerate(value.items()):
            if _secret_key(k):
                # Numeric token counters stay; every other secret-named
                # value drops regardless of type.
                if not (
                    str(k) in NUMERIC_ALLOW_KEYS
                    and (v is None or isinstance(v, (int, float, bool)))
                ):
                    redacted = True
                    continue
            # Keys can carry canaries too — regex-redact + bound, and drop
            # the entry if the redaction made the key ambiguous.
            key_text, key_red, key_trunc = redact_text(str(k), 500)
            redacted = redacted or key_red
            truncated = truncated or key_trunc
            if i >= max_list:
                truncated = True
                break
            v2, v_red, v_trunc = _scrub(v, max_depth, max_list, max_str, depth + 1)
            redacted = redacted or v_red
            truncated = truncated or v_trunc
            out[key_text] = v2
        return out, redacted, truncated
    if isinstance(value, (list, tuple)):
        if depth >= max_depth:
            return ["…"], False, True
        out = []
        redacted = False
        truncated = False
        for i, item in enumerate(value):
            if i >= max_list:
                truncated = True
                break
            v2, v_red, v_trunc = _scrub(item, max_depth, max_list, max_str, depth + 1)
            redacted = redacted or v_red
            truncated = truncated or v_trunc
            out.append(v2)
        return out, redacted, truncated
    if isinstance(value, str):
        text, redacted, truncated = redact_text(value, max_str)
        return text, redacted, truncated
    if isinstance(value, (int, float, bool)) or value is None:
        return value, False, False
    # Unknown scalar-ish type — bound its repr rather than serialize an
    # arbitrary object graph.
    text, redacted, truncated = redact_text(str(value), max_str)
    return text, True or redacted, truncated


# Budget tiers: try the loosest first; tighten until the serialized
# payload fits. Never emits a raw-cut string.
_TIERS = [(5, 25, 500), (4, 15, 200), (3, 8, 100), (2, 5, 60)]

SUMMARY_BUDGET = 2000


def bound_payload(value, budget: int = SUMMARY_BUDGET):
    """Scrub + structure-bound a payload → (payload, redacted, truncated).

    Progressive tiers keep the JSON valid at every cutoff — if even the
    tightest tier overflows, the structure collapses to a marker dict.
    """
    redacted = False
    truncated = False
    for max_depth, max_list, max_str in _TIERS:
        out, red, trunc = _scrub(value, max_depth, max_list, max_str)
        redacted = redacted or red
        truncated = truncated or trunc
        try:
            size = len(json.dumps(out, default=str))
        except (ValueError, TypeError):
            out, truncated = {"_unserializable": True}, True
            break
        if size <= budget:
            return out, redacted, truncated
        truncated = True
    return {"_truncated": True}, True, True


# ---------------------------------------------------------------------------
# URL sanitization
# ---------------------------------------------------------------------------


def sanitize_url(url):
    """Keep scheme+host+path only when it's a plain http/https URL.

    Userinfo, query, fragment and non-http(s) schemes never reach the
    observability surface; the path itself is regex-redacted last.
    """
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = redact_secrets(parts.path or "/")[0]
    return urlunsplit((parts.scheme, parts.hostname, path, "", ""))


# ---------------------------------------------------------------------------
# Per-capability payload projection
# ---------------------------------------------------------------------------

# Args allowed per capability — everything else is dropped.
_ARG_ALLOWLISTS = {
    "terminal": {"command"},
    "read_terminal": {"terminal_id", "offset", "max_chars", "wait_ms"},
    "close_terminal": {"terminal_id"},
    "read_file": {"path", "start_page", "end_page"},
    "search_files": {"mode", "pattern", "path"},
    "write_file": {"path"},
    "doc_list": {"limit", "offset"},
    "doc_inspect": {"document_id"},
    "doc_search": {"query", "limit"},
    "web_search": {"query"},
    "web_fetch": {"url", "offset", "max_chars"},
    "agent_ask_user": {"question", "options", "multi_select"},
    "datetime_now": {"timezone"},
    "run_subagent": {"task", "capabilities"},
    "read_subagent": {"sub_agent_id"},
    "skills_list": set(),
    "skills_load": {"name"},
    "skills_read_resource": {"name", "path"},
    "artifact_create": {"path", "format", "change_summary"},
    "artifact_inspect": {"artifact_id"},
    "artifact_revise": {"artifact_id", "base_revision_id", "change_summary"},
    "artifact_adopt": {"path", "change_summary"},
    "artifact_history": {"artifact_id"},
    "artifact_restore": {"artifact_id", "revision_id", "change_summary"},
    "artifact_export_pdf": {"artifact_id"},
    "capabilities_search": {"query", "limit"},
    "capabilities_load": {"names"},
    "memory_recall": {"query", "limit"},
    "memory_store": {"snippet"},
    "memory_remember_fact": {"entity", "predicate", "object"},
    "memory_query_facts": {"entity", "predicate", "object"},
    "memory_update": set(),
}

# Sensitive readers — the result is never the raw body, just safe metadata.
_METADATA_ONLY_RESULTS = {
    "read_file",
    "doc_list",
    "doc_inspect",
    "memory_recall",
    "memory_store",
    "memory_remember_fact",
    "memory_query_facts",
    "memory_update",
    "skills_read_resource",
}

_BROWSER_ARG_KEYS = {"action", "mode", "profile", "url"}
_BROWSER_RESULT_KEYS = {
    "status",
    "screenshot",
    "staged",
    "evidence",
    "bytes",
    "truncated",
}

_TRACE_KEYS = ("fusion", "lexical_hits", "semantic_hits", "expanded", "degraded")


def _scalar_str(value) -> str | None:
    """Only plain scalar strings make it into browser/tool allowlists —
    a dict or list sneaking into `args.value` is not an argument."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _workspace_ref(value) -> str | None:
    """Evidence refs must be workspace-relative paths — redact first
    (a >300-char path is rejected, never cut mid-secret), no traversal,
    absolute, Windows/UNC, URL, or inline-data refs."""
    if not isinstance(value, str) or not value:
        return None
    ref = redact_secrets(value)[0]
    if len(ref) > 300:
        return None
    lowered = ref.lower()
    if "://" in lowered or lowered.startswith(("file:", "blob:", "javascript:", "data:")):
        return None
    if ref.startswith(("/", "\\")) or "\\" in ref or ":" in ref:
        return None
    if ".." in ref.split("/") or "\\" in ref:
        return None
    return ref


def _project_browser_args(args: dict):
    out = {}
    redacted = False
    for key in _BROWSER_ARG_KEYS:
        if key not in args:
            continue
        if key == "action" and args.get("action") == "navigate":
            # navigate carries the URL in `value` — project it into `url`
            url = sanitize_url(_scalar_str(args.get("value")))
            if url:
                out["url"] = url
            out["action"] = "navigate"
            continue
        value = _scalar_str(args[key])
        if value is None:
            redacted = True
            continue
        out[key] = sanitize_url(value) if key == "url" else value
    if set(args) - _BROWSER_ARG_KEYS - ({"value"} if args.get("action") == "navigate" else set()):
        redacted = True
    return out, redacted or len(out) != len(args)


def _project_browser_result(result: dict):
    out = {}
    for key in _BROWSER_RESULT_KEYS:
        if key not in result:
            continue
        value = result[key]
        if key in ("screenshot", "staged", "evidence"):
            ref = _workspace_ref(value)
            if ref is not None:
                out[key] = ref
        elif key in ("bytes", "truncated"):
            if isinstance(value, (int, bool)):
                out[key] = value
        elif key == "status":
            scalar = _scalar_str(value)
            if scalar is not None:
                out[key] = redact_secrets(scalar)[0][:200]
        else:
            scalar = _scalar_str(value)
            if scalar is not None:
                out[key] = redact_secrets(scalar)[0][:200]
    return out


def _project_terminal_result(result: dict):
    allowed = {
        "terminal_id",
        "status",
        "pid",
        "exit_code",
        "stdout_bytes",
        "stderr_bytes",
        "truncated",
    }
    return {k: v for k, v in result.items() if k in allowed}


def _project_doc_search(args: dict, result) -> dict:
    """Query redacted+bounded; trace keeps its five named fields only;
    citations bounded to 10 items x 500 chars."""
    out = {}
    query, _, _ = redact_text(str(args.get("query", "")), 500)
    out["query"] = query
    if isinstance(result, dict):
        raw_results = result.get("results")
        results_list = raw_results if isinstance(raw_results, list) else []
        trace = result.get("trace")
        if isinstance(trace, dict):
            safe_trace = {}
            for key in _TRACE_KEYS:
                if key not in trace:
                    continue
                if key == "degraded":
                    # Only a list of scalars is a known shape.
                    if isinstance(trace[key], list) and all(
                        isinstance(item, (str, int, float, bool)) for item in trace[key]
                    ):
                        safe_trace[key] = [
                            redact_text(str(item), 200)[0] for item in trace[key][:10]
                        ]
                else:
                    v = trace[key]
                    if isinstance(v, (int, bool)):
                        safe_trace[key] = v
                    else:
                        scalar = _scalar_str(v)
                        if scalar is not None:
                            safe_trace[key] = redact_text(scalar, 100)[0]
            out["trace"] = safe_trace
        sources = []
        for item in results_list[:10]:
            if not isinstance(item, dict):
                continue
            excerpt, _, _ = redact_text(str(item.get("text", "")), 500)
            sources.append(
                {
                    "chunk_id": item.get("chunk_id"),
                    "document_id": item.get("document_id"),
                    "source_path": item.get("source_path"),
                    "heading_path": item.get("heading_path"),
                    "page_number": item.get("page_number"),
                    "sheet_name": item.get("sheet_name"),
                    "excerpt": excerpt,
                }
            )
        out["results"] = sources
        out["count"] = len(results_list)
    return out


def _project_artifact_result(result) -> dict:
    if not isinstance(result, dict):
        return None
    allowed = {
        "artifact_id",
        "revision_id",
        "revision_number",
        "format",
        "path",
        "export_status",
        "renderer",
        "pdf_artifact_id",
        "pdf_path",
        "error",
        "status",
        "tracking_status",
        "revisions",
    }
    return {k: result[k] for k in allowed if k in result}


def _project_metadata_only(result) -> dict:
    out = {}
    if isinstance(result, dict):
        for key in ("path", "count", "status", "error", "truncated"):
            if key in result:
                out[key] = result[key]
        if "documents" in result and isinstance(result["documents"], list):
            out["documents"] = [
                {
                    k: d.get(k)
                    for k in ("document_id", "display_name", "mime_type", "status")
                    if k in d
                }
                for d in result["documents"][:25]
                if isinstance(d, dict)
            ]
    return out


def _parse_payload(raw):
    """JSON string → parsed value; malformed → sentinel so callers can
    fail closed instead of echoing raw text."""
    if isinstance(raw, str):
        try:
            return json.loads(raw), False
        except (ValueError, TypeError):
            return raw, True
    return raw, False


def project_args(capability_name: str, args):
    """Args as the observability surface may show them.

    Returns (payload, redacted, truncated). Malformed strings fail closed
    to a bounded redacted string — never raw pass-through."""
    redacted = False
    parsed, malformed = _parse_payload(args)
    if capability_name.startswith("browser_") and not isinstance(parsed, dict):
        return None, parsed is not None, False
    if malformed:
        text, red, trunc = redact_text(str(parsed), 500)
        return text, True, trunc
    if parsed is None:
        return None, False, False
    if not isinstance(parsed, dict):
        text, red, trunc = redact_text(str(parsed), 500)
        return text, red, trunc

    if capability_name.startswith("browser_"):
        out, redacted = _project_browser_args(parsed)
    else:
        allowlist = _ARG_ALLOWLISTS.get(capability_name)
        if allowlist is not None:
            out = {}
            for key in allowlist:
                if key not in parsed:
                    continue
                if capability_name == "web_fetch" and key == "url":
                    out[key] = sanitize_url(parsed[key])
                else:
                    out[key] = parsed[key]
            redacted = len(out) != len(parsed)
        else:
            out = parsed
    bounded, scrub_red, truncated = bound_payload(out)
    return bounded, redacted or scrub_red, truncated


def project_result(capability_name: str, result):
    """Result as the observability surface may show it.

    Returns (payload, redacted, truncated). Sensitive capabilities fail
    closed on non-object results — a private body never passes raw."""
    parsed, malformed = _parse_payload(result)
    if malformed:
        # Unparseable text: regex-redact + bound only when nothing else is
        # known — for sensitive tools fail closed entirely.
        if (
            capability_name in _METADATA_ONLY_RESULTS
            or capability_name.startswith(("browser_", "doc_", "artifact_", "memory_"))
            or capability_name
            in ("read_file", "terminal", "read_terminal", "close_terminal", "agent_ask_user")
        ):
            return None, True, False
        text, red, trunc = redact_text(str(parsed), 500)
        return text, True, trunc
    if parsed is None:
        return None, False, False

    sensitive = (
        capability_name in _METADATA_ONLY_RESULTS
        or capability_name.startswith(("browser_", "artifact_", "memory_"))
        or capability_name
        in (
            "read_file",
            "doc_list",
            "doc_inspect",
            "terminal",
            "read_terminal",
            "close_terminal",
            "agent_ask_user",
        )
    )
    if sensitive and not isinstance(parsed, dict):
        return None, True, False

    if capability_name.startswith("browser_"):
        out = _project_browser_result(parsed)
        bounded, red, trunc = bound_payload(out)
        return bounded, True or red, trunc
    if capability_name in ("terminal", "read_terminal", "close_terminal"):
        out = _project_terminal_result(parsed)
        bounded, red, trunc = bound_payload(out)
        return bounded, True or red, trunc
    if capability_name == "doc_search":
        out = _project_doc_search({}, parsed)
        bounded, red, trunc = bound_payload(out, budget=7000)
        return bounded, True or red, trunc
    if capability_name == "agent_ask_user":
        out = {"answered": parsed.get("response") is not None}
        bounded, red, trunc = bound_payload(out)
        return bounded, True or red, trunc
    if capability_name.startswith("artifact_"):
        out = _project_artifact_result(parsed)
        bounded, red, trunc = bound_payload(out)
        return bounded, True or red, trunc
    if capability_name in _METADATA_ONLY_RESULTS:
        out = _project_metadata_only(parsed)
        bounded, red, trunc = bound_payload(out)
        return bounded, True or red, trunc

    # Generic path — secret keys out recursively, strings scrubbed,
    # structure bounded to budget.
    return bound_payload(parsed)
