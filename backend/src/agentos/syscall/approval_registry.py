"""Process-global registry for pending approval events (Ticket 04).

When the syscall mediator encounters a capability that requires approval,
it creates an ApprovalRequest row and registers an asyncio.Event here.
The approval API (POST /api/approvals/{id}/approve|reject) looks up the
event by approval_id, updates the DB row, and sets the event — unblocking
the mediator.

Also tracks session-scoped approval allowlists: when the operator approves
with "remember for this session," the approval is stored at one of three
scope levels:

  - EXACT:      same capability + same args (e.g. `cd abc` only)
  - SAME_VERB:  same capability + same command verb (e.g. all `cd *`)
  - CAPABILITY: same capability, any args (e.g. all terminal calls)

Subsequent calls that match the stored scope skip the approval gate.

This is intentionally process-local (in-memory). For multi-process deployments
a Redis/pubsub mechanism would be needed, but v0.1 is single-process.
"""

import asyncio
import fnmatch
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RememberScope(StrEnum):
    EXACT = "exact"
    SAME_VERB = "same_verb"
    PATTERN = "pattern"
    CAPABILITY = "capability"


def _args_hash(capability: str, args: dict[str, Any]) -> str:
    """Stable hash of capability + args for EXACT scope lookup."""
    payload = json.dumps({"cap": capability, "args": args}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _extract_verb(capability: str, args: dict[str, Any]) -> str | None:
    """Extract the command verb for SAME_VERB scope.

    For `terminal` capability, the verb is the first word of the `command` arg.
    Returns None if no verb can be extracted (falls back to EXACT).
    """
    if capability == "terminal":
        command = args.get("command", "")
        if isinstance(command, str) and command.strip():
            return command.strip().split()[0].lower()
    # For other capabilities, verb-based matching doesn't apply —
    # the user should use CAPABILITY scope instead.
    return None


def _extract_command_str(capability: str, args: dict[str, Any]) -> str | None:
    """Extract a command string for PATTERN scope matching.

    For `terminal`, returns the full command string.
    For other capabilities, returns a stringified version of the args
    (so patterns can match against key args).
    """
    if capability == "terminal":
        command = args.get("command", "")
        if isinstance(command, str):
            return command.strip()
    # For non-terminal capabilities, stringify the args for pattern matching
    # e.g. mcp.playwright.browser_navigate({url: "..."}) → 'url=https://...'
    parts = []
    for k, v in sorted(args.items()):
        parts.append(f"{k}={v}")
    return " ".join(parts) if parts else None


@dataclass
class PendingApproval:
    """Tracks a pending approval and its resolution."""

    event: asyncio.Event
    decision: str | None = None  # "approved" or "rejected" — set by the API
    decided_by: str | None = None
    remember: bool = False  # if True, add to session allowlist on approve
    remember_scope: RememberScope = RememberScope.EXACT
    remember_pattern: str | None = None  # wildcard pattern for PATTERN scope (e.g. "cd *")


class ApprovalEventRegistry:
    """Process-global registry of pending approval events + session allowlists."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        # session_id → set of scope keys that are pre-approved
        # scope keys are prefixed by scope type:
        #   "exact:{hash}"       — exact args match
        #   "verb:{cap}:{verb}"  — same command verb
        #   "cap:{cap}"          — entire capability
        self._session_allowlist: dict[str, set[str]] = {}

    def register(self, approval_id: str) -> PendingApproval:
        """Register a new pending approval. Returns the tracker."""
        pa = PendingApproval(event=asyncio.Event())
        self._pending[approval_id] = pa
        return pa

    def get(self, approval_id: str) -> PendingApproval | None:
        return self._pending.get(approval_id)

    def resolve(
        self,
        approval_id: str,
        decision: str,
        decided_by: str,
        remember: bool = False,
        remember_scope: RememberScope = RememberScope.EXACT,
        remember_pattern: str | None = None,
    ) -> bool:
        """Resolve a pending approval. Returns True if found."""
        pa = self._pending.get(approval_id)
        if pa is None:
            return False
        pa.decision = decision
        pa.decided_by = decided_by
        pa.remember = remember
        pa.remember_scope = remember_scope
        pa.remember_pattern = remember_pattern
        pa.event.set()
        return True

    def cleanup(self, approval_id: str) -> None:
        """Remove a resolved approval from the registry."""
        self._pending.pop(approval_id, None)

    def list_pending_ids(self) -> list[str]:
        return list(self._pending.keys())

    # --- Session-scoped allowlist ---

    def is_session_approved(self, session_id: str, capability: str, args: dict[str, Any]) -> bool:
        """Check if this capability+args was previously approved in this session.

        Checks all four scope levels:
          1. CAPABILITY — if the entire capability is allowlisted, any args match
          2. PATTERN — if any stored pattern matches the command string
          3. SAME_VERB — if the verb is allowlisted, same-verb commands match
          4. EXACT — if the exact args hash is allowlisted, exact match
        """
        allowed = self._session_allowlist.get(session_id)
        if not allowed:
            return False

        # 1. Capability scope — broadest
        if f"cap:{capability}" in allowed:
            return True

        # 2. Pattern scope — wildcard match against command string
        command_str = _extract_command_str(capability, args)
        if command_str:
            for key in allowed:
                if key.startswith(f"pattern:{capability}:"):
                    pattern = key[len(f"pattern:{capability}:") :]
                    if fnmatch.fnmatch(command_str, pattern):
                        return True

        # 3. Verb scope — for terminal commands
        verb = _extract_verb(capability, args)
        if verb and f"verb:{capability}:{verb}" in allowed:
            return True

        # 4. Exact scope — narrowest
        if _args_hash(capability, args) in allowed:
            return True

        return False

    def remember_approval(
        self,
        session_id: str,
        capability: str,
        args: dict[str, Any],
        scope: RememberScope = RememberScope.EXACT,
        pattern: str | None = None,
    ) -> None:
        """Add an approval to the session allowlist at the given scope."""
        if session_id not in self._session_allowlist:
            self._session_allowlist[session_id] = set()

        if scope == RememberScope.CAPABILITY:
            self._session_allowlist[session_id].add(f"cap:{capability}")
        elif scope == RememberScope.PATTERN:
            if pattern and capability:
                self._session_allowlist[session_id].add(f"pattern:{capability}:{pattern}")
            else:
                # No pattern provided — fall back to exact
                self._session_allowlist[session_id].add(_args_hash(capability, args))
        elif scope == RememberScope.SAME_VERB:
            verb = _extract_verb(capability, args)
            if verb:
                self._session_allowlist[session_id].add(f"verb:{capability}:{verb}")
            else:
                # No verb extractable — fall back to exact
                self._session_allowlist[session_id].add(_args_hash(capability, args))
        else:  # EXACT
            self._session_allowlist[session_id].add(_args_hash(capability, args))

    def clear_session(self, session_id: str) -> None:
        """Clear the allowlist for a session (e.g. on session end)."""
        self._session_allowlist.pop(session_id, None)


# Global instance
approval_registry = ApprovalEventRegistry()
