"""Process-global registry for pending approval events (Ticket 04).

When the syscall mediator encounters a capability that requires approval,
it creates an ApprovalRequest row and registers an asyncio.Event here.
The approval API (POST /api/approvals/{id}/approve|reject) looks up the
event by approval_id, updates the DB row, and sets the event — unblocking
the mediator.

Also tracks session-scoped approval allowlists: when the operator approves
with "remember for this session," the (session_id, capability, args_hash)
triple is stored. Subsequent calls with the same capability+args in the
same session skip the approval gate entirely.

This is intentionally process-local (in-memory). For multi-process deployments
a Redis/pubsub mechanism would be needed, but v0.1 is single-process.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _args_hash(capability: str, args: dict[str, Any]) -> str:
    """Stable hash of capability + args for allowlist lookup."""
    payload = json.dumps({"cap": capability, "args": args}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class PendingApproval:
    """Tracks a pending approval and its resolution."""

    event: asyncio.Event
    decision: str | None = None  # "approved" or "rejected" — set by the API
    decided_by: str | None = None
    remember: bool = False  # if True, add to session allowlist on approve


class ApprovalEventRegistry:
    """Process-global registry of pending approval events + session allowlists."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        # session_id → set of args_hashes that are pre-approved for this session
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
    ) -> bool:
        """Resolve a pending approval. Returns True if found."""
        pa = self._pending.get(approval_id)
        if pa is None:
            return False
        pa.decision = decision
        pa.decided_by = decided_by
        pa.remember = remember
        pa.event.set()
        return True

    def cleanup(self, approval_id: str) -> None:
        """Remove a resolved approval from the registry."""
        self._pending.pop(approval_id, None)

    def list_pending_ids(self) -> list[str]:
        return list(self._pending.keys())

    # --- Session-scoped allowlist ---

    def is_session_approved(self, session_id: str, capability: str, args: dict[str, Any]) -> bool:
        """Check if this capability+args was previously approved in this session."""
        allowed = self._session_allowlist.get(session_id)
        if not allowed:
            return False
        return _args_hash(capability, args) in allowed

    def remember_approval(self, session_id: str, capability: str, args: dict[str, Any]) -> None:
        """Add a capability+args to the session allowlist."""
        if session_id not in self._session_allowlist:
            self._session_allowlist[session_id] = set()
        self._session_allowlist[session_id].add(_args_hash(capability, args))

    def clear_session(self, session_id: str) -> None:
        """Clear the allowlist for a session (e.g. on session end)."""
        self._session_allowlist.pop(session_id, None)


# Global instance
approval_registry = ApprovalEventRegistry()
