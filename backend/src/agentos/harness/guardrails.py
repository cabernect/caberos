"""Output guardrails — validate/redact the model's final answer before it
reaches the user (custom harness implementation).

Three guardrails, run in order:
1. Secret redaction — scan for API keys, tokens, passwords; replace with [REDACTED]
2. Prompt injection check — detect instruction-like patterns leaking from file contents
3. Context leakage check — detect workspace paths, system prompt fragments, internal IDs

Each guardrail returns a (possibly modified) string and a list of warnings.
The harness logs warnings to the audit trail and emits them as SSE events.
"""

import re
from dataclasses import dataclass, field

# Patterns + helper live in agentos.redaction — imported under the private
# names so existing tests/imports keep working.
from ..redaction import SECRET_PATTERNS as _SECRET_PATTERNS  # noqa: F401
from ..redaction import redact_secrets as _redact_secrets


@dataclass
class GuardrailResult:
    """Result of running all guardrails on a model output."""

    content: str
    warnings: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)  # what was redacted (sanitized)


# ---------------------------------------------------------------------------
# 1. Secret redaction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2. Prompt injection detection
# ---------------------------------------------------------------------------

# Patterns that suggest the model is echoing injected instructions from file
# contents rather than its own reasoning. These are heuristics — not perfect,
# but catch the common patterns.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "instruction override",
        re.compile(
            r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?"
            r"|disregard\s+(?:the\s+)?(?:above|previous)\s+(?:system\s+)?prompt"
            r"|you\s+are\s+now\s+(?:a|an)\s+(?:different|new|jailbroken|unrestricted)"
            r"|forget\s+(?:everything|all\s+(?:your\s+)?rules|previous\s+instructions))",
        ),
    ),
    (
        "role reset",
        re.compile(
            r"(?i)(system\s*:\s*you\s+are"
            r"|\[INST\]|\[/INST\]"
            r"|<\|system\|>|<\|im_start\|>|<\|im_end\|>)",
        ),
    ),
    (
        "instruction echo",
        re.compile(
            r"(?i)(as\s+an?\s+AI\s+language\s+model[^.]*,\s*i\s+(?:am|cannot|can)\s+not"
            r"|I\s+am\s+programmed\s+to\s+(?:follow|never|always))",
        ),
    ),
]


def _check_prompt_injection(content: str) -> list[str]:
    """Detect prompt injection patterns leaking into the output."""
    warnings: list[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            warnings.append(
                f"Possible prompt injection detected: '{name}' pattern found "
                f"({len(matches)} occurrence(s)). Output may contain echoed "
                f"file instructions rather than model reasoning."
            )
    return warnings


# ---------------------------------------------------------------------------
# 3. Context leakage detection
# ---------------------------------------------------------------------------

# Patterns that suggest internal context is leaking into the user-facing output.
_LEAKAGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Absolute file paths outside a typical workspace (e.g. /Users/, /home/, C:\)
    (
        "absolute home path",
        re.compile(r"(/Users/[A-Za-z0-9_\-]+|/home/[A-Za-z0-9_\-]+|C:\\Users\\[A-Za-z0-9_\-]+)"),
    ),
    # Agent home dir path (should never be exposed)
    (
        "agent home path",
        re.compile(r"~/agentos/agents/[A-Za-z0-9_\-]+"),
    ),
    # System prompt fragments — soul/persona/task markers that shouldn't leak
    (
        "system prompt fragment",
        re.compile(r"(?i)(\[SOUL\]|\[PERSONA\]|\[TASK\]|\[SYSTEM\]|\[INSTRUCTIONS\])"),
    ),
    # UUIDs that look like internal IDs (run_id, session_id, approval_id)
    # Only flag if there are 3+ UUIDs — one might be a legitimate reference
    (
        "multiple internal UUIDs",
        re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    ),
]


def _check_context_leakage(content: str) -> tuple[list[str], str]:
    """Detect context leakage. Returns (warnings, possibly_modified_content)."""
    warnings: list[str] = []
    modified = content

    for name, pattern in _LEAKAGE_PATTERNS:
        matches = pattern.findall(content)
        if not matches:
            continue

        if name == "multiple internal UUIDs":
            if len(matches) >= 3:
                warnings.append(
                    f"Context leakage: {len(matches)} internal UUIDs found in output. "
                    f"Internal IDs should not be exposed to the user."
                )
        elif name == "absolute home path":
            warnings.append(
                f"Context leakage: absolute home path(s) found in output "
                f"({len(matches)} occurrence(s)). File paths outside the workspace "
                f"should not be exposed."
            )
            # Redact the home path
            modified = pattern.sub("[PATH]", modified)
        elif name == "agent home path":
            warnings.append(
                "Context leakage: agent home directory path found in output. "
                "The agent home dir is internal and should not be exposed."
            )
            modified = pattern.sub("~/agentos/agents/[REDACTED]", modified)
        elif name == "system prompt fragment":
            warnings.append(
                f"Context leakage: system prompt fragment(s) found in output "
                f"({len(matches)} occurrence(s)). Internal prompt markers "
                f"should not appear in user-facing responses."
            )

    return warnings, modified


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_guardrails(content: str) -> GuardrailResult:
    """Run all guardrails on the model's final answer.

    Order:
    1. Secret redaction (modifies content)
    2. Prompt injection check (warnings only — doesn't modify)
    3. Context leakage check (warnings + may redact paths)

    Returns GuardrailResult with the (possibly modified) content and warnings.
    """
    warnings: list[str] = []
    redactions: list[str] = []

    # 1. Secret redaction
    content, secret_redactions = _redact_secrets(content)
    redactions.extend(secret_redactions)
    if secret_redactions:
        warnings.append(
            f"Secret(s) redacted from output: {', '.join(secret_redactions)}. "
            f"The agent may have read a file containing credentials."
        )

    # 2. Prompt injection check
    injection_warnings = _check_prompt_injection(content)
    warnings.extend(injection_warnings)

    # 3. Context leakage check
    leakage_warnings, content = _check_context_leakage(content)
    warnings.extend(leakage_warnings)

    return GuardrailResult(content=content, warnings=warnings, redactions=redactions)


# ---------------------------------------------------------------------------
# Input guardrails — run on the user's message before it enters the pipeline
# ---------------------------------------------------------------------------


def apply_input_guardrails(content: str) -> GuardrailResult:
    """Run guardrails on the user's inbound message.

    Catches:
    - Secrets the user pasted (redacted before storage — don't persist API keys in message history)
    - Prompt injection attempts (warned — the message still goes through, but the operator
      is alerted that the user may be trying to manipulate the agent)

    Returns GuardrailResult. The content may be modified (secrets redacted).
    Warnings are emitted as SSE events so the operator sees them live.
    """
    warnings: list[str] = []
    redactions: list[str] = []

    # 1. Secret redaction — don't persist API keys in the message history
    content, secret_redactions = _redact_secrets(content)
    redactions.extend(secret_redactions)
    if secret_redactions:
        warnings.append(
            f"Secret(s) redacted from your message: {', '.join(secret_redactions)}. "
            f"For security, the key was replaced with [REDACTED] before processing."
        )

    # 2. Prompt injection detection — warn but don't block
    injection_warnings = _check_prompt_injection(content)
    for w in injection_warnings:
        # Rephrase for input context
        warnings.append(
            w.replace(
                "Output may contain echoed file instructions rather than model reasoning.",
                "The user message contains instruction-override patterns. "
                "The agent will still process the message, but this is logged for audit.",
            )
        )

    return GuardrailResult(content=content, warnings=warnings, redactions=redactions)
