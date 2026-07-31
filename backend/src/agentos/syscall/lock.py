"""Per-Session lock — at most one Run per Session at a time (D19 step 6).

Different sessions for the same agent run concurrently.
Same session serializes (don't interleave turns in one conversation).
"""

import asyncio


class SessionLockManager:
    """In-process asyncio lock keyed by session_id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]


# Global instance
session_locks = SessionLockManager()
