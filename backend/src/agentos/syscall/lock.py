"""Per-Contact lock — at most one Run per Contact at a time (D19 step 6)."""

import asyncio


class ContactLockManager:
    """In-process asyncio lock keyed by contact_id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, contact_id: str) -> asyncio.Lock:
        if contact_id not in self._locks:
            self._locks[contact_id] = asyncio.Lock()
        return self._locks[contact_id]


# Global instance
contact_locks = ContactLockManager()
