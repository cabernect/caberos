"""Session-activity fan-out — transient signals for internal session work.

Close-time summary + durable learning run in the background (sweeper, lazy
trigger, explicit close). These payloads are UI state only: nothing is
persisted and a full subscriber queue silently drops the frame — unlike
notifications, which write an inbox row first and never drop.
"""

import asyncio

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def broadcast(payload: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def broadcast_close(session_id: str, agent_id: str, phase: str) -> None:
    """phase: started | finished | failed — one close attempt's lifecycle."""
    broadcast(
        {
            "type": "session_activity",
            "kind": "session_close",
            "phase": phase,
            "session_id": session_id,
            "agent_id": agent_id,
        }
    )
