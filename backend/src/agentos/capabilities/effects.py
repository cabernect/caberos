"""Capability effect classification (v0.2 foundations).

Effects describe what a capability *can do* to the world, independent of
`egress` (network reach) and `require_approval` (human gate). They are the
trusted classification Plan Mode and future policy checks read — a model,
skill, or plan can never change them.

Classes form a coarse ladder:

    read             observes state only; no durable mutation
    workspace_write  writes inside the agent workspace
    local_execute    executes local processes (terminal)
    external_write   mutates state outside this machine (email, POST, publish)
    destructive      irreversible loss: deletes or overwrites data

A capability may declare several classes — the honest set of what a call
can cause. `read` alone means read-only; anything else is mutating.
"""

from typing import Literal

CapabilityEffect = Literal[
    "read",
    "workspace_write",
    "local_execute",
    "external_write",
    "destructive",
]

ALL_EFFECTS: frozenset[str] = frozenset(
    {"read", "workspace_write", "local_execute", "external_write", "destructive"}
)

READ_ONLY: frozenset[str] = frozenset({"read"})

# Unknown or untrusted tools are assumed mutating — never silently read-only.
DEFAULT_MUTATING: frozenset[str] = frozenset({"external_write"})


def normalize_effects(effects: frozenset[str] | set[str] | list[str] | None) -> frozenset[str]:
    """Validate an effect set. Invalid or empty input means mutating."""
    if not effects:
        return DEFAULT_MUTATING
    normalized = frozenset(effects)
    unknown = normalized - ALL_EFFECTS
    if unknown:
        raise ValueError(f"Unknown capability effects: {sorted(unknown)}")
    return normalized


def is_read_only(effects: frozenset[str] | set[str] | None) -> bool:
    """Whether the capability can only observe state."""
    return normalize_effects(effects) == READ_ONLY


def effects_from_mcp_annotations(annotations: dict | None) -> frozenset[str]:
    """Classify an MCP tool from its protocol annotations.

    MCP ToolAnnotations: readOnlyHint, destructiveHint, idempotentHint,
    openWorldHint. Hints inform but never prove safety — an unannotated
    tool defaults to mutating rather than read-only.
    """
    if not isinstance(annotations, dict):
        return DEFAULT_MUTATING

    if annotations.get("readOnlyHint") is True:
        return READ_ONLY

    effects: set[str] = {"external_write"}
    if annotations.get("destructiveHint") is True:
        effects.add("destructive")
    return frozenset(effects)
