"""Process-global registry for pending elicitation events.

When the agent calls `agent.ask_user(question)`, the mediator creates an
ElicitationRequest row and registers an asyncio.Event here. The elicitation
API (POST /api/elicitation/{id}/respond) looks up the event by elicitation_id,
updates the DB row, and sets the event — unblocking the mediator.

Process-local (in-memory), same rationale as the approval registry.
"""

import asyncio
from dataclasses import dataclass


@dataclass
class PendingElicitation:
    """Tracks a pending elicitation and its resolution."""

    event: asyncio.Event
    response: str | None = None  # user's answer — set by the API
    responded_by: str | None = None


class ElicitationEventRegistry:
    """Process-global registry of pending elicitation events."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingElicitation] = {}

    def register(self, elicitation_id: str) -> PendingElicitation:
        """Register a new pending elicitation. Returns the tracker."""
        pe = PendingElicitation(event=asyncio.Event())
        self._pending[elicitation_id] = pe
        return pe

    def get(self, elicitation_id: str) -> PendingElicitation | None:
        return self._pending.get(elicitation_id)

    def resolve(
        self, elicitation_id: str, response: str, responded_by: str
    ) -> bool:
        """Resolve a pending elicitation. Returns True if found."""
        pe = self._pending.get(elicitation_id)
        if pe is None:
            return False
        pe.response = response
        pe.responded_by = responded_by
        pe.event.set()
        return True

    def cancel(self, elicitation_id: str) -> bool:
        """Cancel a pending elicitation (e.g. run aborted). Returns True if found."""
        pe = self._pending.get(elicitation_id)
        if pe is None:
            return False
        pe.response = "[cancelled]"
        pe.event.set()
        return True

    def cleanup(self, elicitation_id: str) -> None:
        """Remove a resolved elicitation from the registry."""
        self._pending.pop(elicitation_id, None)

    def list_pending_ids(self) -> list[str]:
        return list(self._pending.keys())


# Global instance
elicitation_registry = ElicitationEventRegistry()
