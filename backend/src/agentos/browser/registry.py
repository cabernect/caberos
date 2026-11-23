"""BrowserRegistry — owns managed browser sessions for the gateway.

Mirrors TerminalRegistry's ownership rules: a session is scoped to its
conversation session — runs in the same session share one browser so a
later run can continue on the page an earlier run left open. Sessionless
runs (scheduled/heartbeat) fall back to run scope. Another session can't
observe or close a browser it didn't open. Idle sessions are reaped (a
Chromium tree idles at ~1 GB RSS — the spike measured this). Stopping a
run preserves its conversation browser; sessionless browsers are closed.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .cdp import BrowserSession
from .runtime import find_browser_binary

IDLE_TIMEOUT_S = 600.0  # session browsers outlive runs — reap after 10 min silent
REAP_INTERVAL_S = 15.0


def _scope_key(session_id: str | None, run_id: str) -> str:
    return f"session:{session_id}" if session_id else f"run:{run_id}"


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
    # exempt from idle reaping (the user may be mid-MFA).
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _profiles_root() -> Path:
    from ..config import settings

    return (settings.db_path.parent / "browser-profiles").resolve()


class BrowserRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _Managed] = {}
        self._reaper_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

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
        # Serialize allocation so concurrent opens cannot launch duplicate
        # processes or acquire the same persistent profile.
        async with self._lock:
            return await self._get_or_open(
                url,
                agent_id,
                session_id,
                run_id,
                research,
                staging_dir,
                profile,
                allowed_domains,
                visible,
            )

    async def _get_or_open(
        self,
        url: str,
        agent_id: str,
        session_id: str | None,
        run_id: str,
        research: bool,
        staging_dir: Path | None,
        profile: str | None,
        allowed_domains: list[str] | None,
        visible: bool,
    ) -> tuple[BrowserSession, str]:
        """Return the session's live browser, or launch one and navigate.

        Keyed by conversation session: a later run in the same session
        reuses the open browser (same tab, same cookies, same page state).
        """
        from .cdp import BrowserError

        key = _scope_key(session_id, run_id)
        existing = self._sessions.get(key)
        if existing and existing.agent_id != agent_id:
            raise BrowserError("browser belongs to another agent")
        if existing and existing.session.alive():
            if profile and profile != existing.profile_name:
                held = (
                    f"profile {existing.profile_name!r}"
                    if existing.profile_name
                    else "an isolated profile"
                )
                raise BrowserError(
                    f"session browser already open with {held} — "
                    "call browser_close first or reuse it"
                )
            if visible and not existing.visible:
                raise BrowserError(
                    "session browser is headless — it cannot be reopened "
                    "visible; call browser_close first"
                )
            # Reopening a different URL means "go there" — navigate the
            # live session rather than silently staying put.
            async with existing.lock:
                await existing.session.navigate(url)
                obs = await existing.session.observe()
            existing.run_id = run_id
            existing.session_id = session_id
            return existing.session, obs.serialize()
        if existing is not None:
            # Dead process still holds its slot — clean it before relaunch.
            await self._close_key(key)

        if profile:
            # One live session per named profile — a second conversation gets an
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
                    f"profile '{profile}' is in use by another session — "
                    "close that browser first or use an isolated session"
                )
            if allowed_domains and not _url_in_scope(url, allowed_domains):
                raise BrowserError(
                    f"url outside profile '{profile}' scope ({', '.join(allowed_domains)}): {url}"
                    " — retry without the profile arg for an isolated session"
                )

        binary = find_browser_binary()
        if binary is None:
            raise BrowserError(
                "runtime_unavailable: no managed browser runtime found — "
                "install it via Settings → Browser or set AGENTOS_BROWSER_BINARY"
            )
        if profile:
            profile_dir = _profiles_root() / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            tmp = None
            session_dir = profile_dir
        else:
            tmp = tempfile.TemporaryDirectory(
                prefix=f"agentos-browser-{run_id[:8]}-", ignore_cleanup_errors=True
            )
            session_dir = Path(tmp.name)
        session = BrowserSession(binary, session_dir, staging_dir=staging_dir)
        try:
            obs = await session.open(
                url, research=research, allowed_domains=allowed_domains, visible=visible
            )
        except BaseException:
            if tmp is not None:
                tmp.cleanup()
            raise
        self._sessions[key] = _Managed(
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

    def get_owned(
        self, run_id: str, agent_id: str, session_id: str | None = None
    ) -> BrowserSession:
        m = self._sessions.get(_scope_key(session_id, run_id))
        if not m or m.agent_id != agent_id or not m.session.alive():
            from .cdp import BrowserError

            raise BrowserError("no open browser session — call browser_open first")
        return m.session

    @asynccontextmanager
    async def owned(
        self, run_id: str, agent_id: str, session_id: str | None = None
    ) -> AsyncIterator[BrowserSession]:
        async with self._lock:
            session = self.get_owned(run_id, agent_id, session_id)
            managed = self._sessions[_scope_key(session_id, run_id)]
            await managed.lock.acquire()
        try:
            yield session
        finally:
            session.last_activity = time.monotonic()
            managed.lock.release()

    async def _close_key(self, key: str) -> bool:
        m = self._sessions.get(key)
        if not m:
            return False
        async with m.lock:
            self._sessions.pop(key)
            try:
                await m.session.close()
            finally:
                if m.profile_dir is not None:
                    m.profile_dir.cleanup()
        return True

    async def close_owned(self, run_id: str, agent_id: str, session_id: str | None = None) -> bool:
        async with self._lock:
            key = _scope_key(session_id, run_id)
            managed = self._sessions.get(key)
            if managed is None:
                return False
            if managed.agent_id != agent_id:
                from .cdp import BrowserError

                raise BrowserError("browser belongs to another agent")
            return await self._close_key(key)

    async def close_for_run(self, run_id: str) -> bool:
        """Stop cleans sessionless runs, not the conversation's browser."""
        async with self._lock:
            return await self._close_key(_scope_key(None, run_id))

    async def shutdown_all(self) -> None:
        async with self._lock:
            for key in list(self._sessions):
                await self._close_key(key)

    def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_idle())

    async def _reap_idle(self) -> None:
        while self._sessions:
            await asyncio.sleep(REAP_INTERVAL_S)
            async with self._lock:
                now = time.monotonic()
                for key, m in list(self._sessions.items()):
                    if m.lock.locked():
                        continue
                    if not m.session.alive() or (
                        not m.visible and now - m.session.last_activity > IDLE_TIMEOUT_S
                    ):
                        await self._close_key(key)


browser_registry = BrowserRegistry()
