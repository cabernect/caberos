"""BrowserRegistry — owns managed browser sessions for the gateway.

Mirrors TerminalRegistry's ownership rules: a session is scoped to
(agent_id, session_id, run_id) — another run can't observe or close a
browser it didn't open. Idle sessions are reaped (a Chromium tree idles at
~1 GB RSS — the spike measured this), and run cancellation must not orphan
processes.

v0.2 scope: one session per run, headless only, isolated temp profiles.
Persistent profiles and visible mode are later W4 slices.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .cdp import BrowserSession
from .runtime import find_browser_binary

IDLE_TIMEOUT_S = 120.0  # reap sessions silent this long — RSS is expensive


@dataclass
class _Managed:
    session: BrowserSession
    agent_id: str
    session_id: str | None
    run_id: str
    profile_dir: tempfile.TemporaryDirectory


class BrowserRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _Managed] = {}  # run_id -> managed session
        self._reaper_task: asyncio.Task | None = None

    async def get_or_open(
        self, url: str, agent_id: str, session_id: str | None, run_id: str
    ) -> tuple[BrowserSession, str]:
        """Return the run's live session, or launch one and navigate."""
        existing = self._sessions.get(run_id)
        if existing and existing.session.alive():
            return existing.session, "reused"

        binary = find_browser_binary()
        if binary is None:
            from .cdp import BrowserError

            raise BrowserError(
                "runtime_unavailable: no managed browser runtime found — "
                "install it via Settings → Dependencies or set AGENTOS_BROWSER_BINARY"
            )
        profile = tempfile.TemporaryDirectory(prefix=f"agentos-browser-{run_id[:8]}-")
        session = BrowserSession(binary, Path(profile.name))
        obs = await session.open(url)
        self._sessions[run_id] = _Managed(
            session=session,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            profile_dir=profile,
        )
        self._ensure_reaper()
        return session, obs.serialize()

    def get_owned(self, run_id: str, agent_id: str) -> BrowserSession:
        m = self._sessions.get(run_id)
        if not m or m.agent_id != agent_id or not m.session.alive():
            from .cdp import BrowserError

            raise BrowserError("no open browser session for this run — call browser_open first")
        return m.session

    async def close_for_run(self, run_id: str) -> bool:
        m = self._sessions.pop(run_id, None)
        if not m:
            return False
        await m.session.close()
        m.profile_dir.cleanup()
        return True

    async def shutdown_all(self) -> None:
        for run_id in list(self._sessions):
            await self.close_for_run(run_id)

    def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_idle())

    async def _reap_idle(self) -> None:
        while self._sessions:
            await asyncio.sleep(15)
            now = time.monotonic()
            for run_id, m in list(self._sessions.items()):
                if not m.session.alive() or now - m.session.last_activity > IDLE_TIMEOUT_S:
                    await self.close_for_run(run_id)


browser_registry = BrowserRegistry()
