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
REAP_INTERVAL_S = 15.0


def _url_in_scope(url: str, domains: list[str]) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


@dataclass
class _Managed:
    session: BrowserSession
    agent_id: str
    session_id: str | None
    run_id: str
    profile_dir: tempfile.TemporaryDirectory | None
    profile_name: str | None = None  # persistent profile in use, if any
    visible: bool = False  # windowed sessions exist for human takeover —
    # exempt from idle reaping (the user may be mid-MFA); run-end,
    # cancel, and shutdown cleanup still apply


def _profiles_root() -> Path:
    from ..config import settings

    return settings.db_path.parent / "browser-profiles"


class BrowserRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _Managed] = {}  # run_id -> managed session
        self._reaper_task: asyncio.Task | None = None

    async def get_or_open(
        self,
        url: str,
        agent_id: str,
        session_id: str | None,
        run_id: str,
        research: bool = False,
        staging_dir: Path | None = None,
        profile: str | None = None,
        allowed_domains: list[str] | None = None,
        visible: bool = False,
    ) -> tuple[BrowserSession, str]:
        """Return the run's live session, or launch one and navigate."""
        from .cdp import BrowserError

        existing = self._sessions.get(run_id)
        if existing and existing.session.alive():
            return existing.session, "reused"

        if profile:
            # One live session per named profile — a second run gets an
            # honest refusal rather than corrupting shared profile state.
            held = next(
                (
                    m
                    for m in self._sessions.values()
                    if m.profile_name == profile and m.session.alive()
                ),
                None,
            )
            if held:
                raise BrowserError(
                    f"profile '{profile}' is in use by another run — "
                    "try again after it finishes or use an isolated session"
                )
            if allowed_domains and not _url_in_scope(url, allowed_domains):
                raise BrowserError(
                    f"url outside profile '{profile}' scope ({', '.join(allowed_domains)}): {url}"
                )

        binary = find_browser_binary()
        if binary is None:
            raise BrowserError(
                "runtime_unavailable: no managed browser runtime found — "
                "install it via Settings → Dependencies or set AGENTOS_BROWSER_BINARY"
            )
        if profile:
            profile_dir = _profiles_root() / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            tmp = None
            session_dir = profile_dir
        else:
            tmp = tempfile.TemporaryDirectory(prefix=f"agentos-browser-{run_id[:8]}-")
            session_dir = Path(tmp.name)
        session = BrowserSession(binary, session_dir, staging_dir=staging_dir)
        obs = await session.open(
            url, research=research, allowed_domains=allowed_domains, visible=visible
        )
        self._sessions[run_id] = _Managed(
            session=session,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            profile_dir=tmp,
            profile_name=profile,
            visible=visible,
        )
        self._ensure_reaper()
        note = obs.serialize()
        if session.fell_back:
            note += (
                "\n(note: research mode fell back to normal load — "
                "site broke with resource blocking)"
            )
        return session, note

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
        if m.profile_dir is not None:
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
            await asyncio.sleep(REAP_INTERVAL_S)
            now = time.monotonic()
            for run_id, m in list(self._sessions.items()):
                if not m.session.alive() or (
                    not m.visible and now - m.session.last_activity > IDLE_TIMEOUT_S
                ):
                    await self.close_for_run(run_id)


browser_registry = BrowserRegistry()
