"""Bundled/local models.dev catalog snapshot (W11).

One immutable bundled JSON ships with the package for immediate offline
operation; operator-approved refreshes are stored as content-hash-named
snapshots under application data with an atomic active-pointer. Every
read is local — lookup/status never touch the network, and the parsed
payload is cached by (sha256, size, mtime) so callers never re-parse
5 MB per entry.

Refresh is an explicit, deduplicated job: a manual redirect loop that
validates HTTPS+origin before every request, a streamed body capped at
16 MiB under a total deadline, decode_catalog validation, and atomic
activation. Corrupt/missing/hash-mismatched state falls back to the
valid bundled snapshot while recording the error separately — a bad
pointer never lies "refreshed".
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from ..ssl_utils import SSL_CERT_PATH
from .catalog_policy import decode_catalog

logger = logging.getLogger(__name__)

CATALOG_URL = "https://models.dev/api.json"
CATALOG_REFRESH_SECONDS = 86400  # one refresh per 24 h while enabled
CATALOG_RETRY_SECONDS = 900  # back off failed automatic refreshes
CATALOG_POLL_SECONDS = 60  # worker tick
CATALOG_MAX_BYTES = 16 * 1024 * 1024
CATALOG_FETCH_TIMEOUT = 15.0  # total deadline, not per-chunk
CATALOG_MAX_REDIRECTS = 3

Fetcher = Callable[[], Awaitable[bytes]]

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _bundled_dir() -> Path:
    return Path(__file__).parent / "data"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_error(exc: BaseException) -> str:
    """Actionable failure text — type + bounded detail, no URLs/keys/body."""
    name = type(exc).__name__
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return f"http_status_{exc.response.status_code}"
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.RequestError):
            return "request_failed"
    except Exception:
        pass
    if isinstance(exc, ValueError):
        return f"invalid:{str(exc)[:160]}"
    return name


class CatalogSnapshot:
    """Local catalog snapshot: bundled immutable file + refreshed store.

    store_dir holds ``snapshots/<sha256>.json`` files plus ``active.json``
    pointing at the activated revision and ``last_error.json`` for the
    last failure (kept separate so an error never fabricates a pointer).
    """

    def __init__(self, store_dir: Path, bundled_path: Path | None = None) -> None:
        self.store_dir = Path(store_dir)
        self.bundled_path = bundled_path or (_bundled_dir() / "models.dev.json")
        self.bundled_manifest_path = self.bundled_path.with_name("models.dev.manifest.json")
        self._require_bundle_manifest = bundled_path is None
        self._snapshots_dir = self.store_dir / "snapshots"
        self._active_file = self.store_dir / "active.json"
        self._error_file = self.store_dir / "last_error.json"
        self._refresh_task: asyncio.Task | None = None
        # Parsed payload cache keyed by (sha, size, mtime_ns).
        self._cache: OrderedDict[str, tuple[str, dict]] = OrderedDict()

    # -- pointer + manifest reads ----------------------------------------

    def _bundled_manifest(self) -> dict | None:
        try:
            if self.bundled_manifest_path.is_file():
                data = json.loads(self.bundled_manifest_path.read_bytes())
                return data if isinstance(data, dict) else None
        except Exception:
            pass
        return None

    def _active(self) -> dict | None:
        try:
            if self._active_file.is_file():
                data = json.loads(self._active_file.read_bytes())
                if isinstance(data, dict) and _SHA_RE.match(str(data.get("sha256", ""))):
                    return data
        except Exception:
            pass
        return None

    def _last_error(self) -> dict | None:
        try:
            if self._error_file.is_file():
                data = json.loads(self._error_file.read_bytes())
                return data if isinstance(data, dict) else None
        except Exception:
            pass
        return None

    # -- payload loading ---------------------------------------------------

    def _decode_path(self, path: Path) -> tuple[str, dict] | None:
        """Hash-verify + decode a snapshot file; cache the parsed payload."""
        try:
            st = path.stat()
        except OSError:
            return None
        if st.st_size > CATALOG_MAX_BYTES or st.st_size == 0:
            return None
        key_source = f"{path}:{st.st_size}:{st.st_mtime_ns}"
        if key_source in self._cache:
            self._cache.move_to_end(key_source)
            return self._cache[key_source]
        try:
            body = path.read_bytes()
            data = decode_catalog(body)
        except (ValueError, OSError):
            return None
        sha = _sha256(body)
        self._cache[key_source] = (sha, data)
        self._cache.move_to_end(key_source)
        while len(self._cache) > 2:
            self._cache.popitem(last=False)
        return sha, data

    def _load(self) -> tuple[str, dict] | None:
        """(sha, payload) of the best valid local snapshot."""
        active = self._active()
        if active:
            path = self._snapshots_dir / f"{active['sha256']}.json"
            loaded = self._decode_path(path)
            if loaded and loaded[0] == active["sha256"]:
                return loaded
        return self._verified_bundle()

    def _verified_bundle(self) -> tuple[str, dict] | None:
        loaded = self._decode_path(self.bundled_path)
        manifest = self._bundled_manifest()
        if manifest is None:
            return None if self._require_bundle_manifest else loaded
        if not loaded or manifest.get("sha256") != loaded[0]:
            return None
        return loaded

    def lookup(self, catalog_provider_id: str, exact_model_id: str) -> dict | None:
        """Exact raw catalog entry, deep-copied so callers can't mutate the
        shared cache. Absent stays None — never guessed."""
        loaded = self._load()
        if not loaded:
            return None
        _, data = loaded
        provider = data.get(catalog_provider_id)
        if not isinstance(provider, dict):
            return None
        models = provider.get("models")
        if not isinstance(models, dict):
            return None
        entry = models.get(exact_model_id)
        return deepcopy(entry) if isinstance(entry, dict) else None

    def models(self, catalog_provider_id: str) -> dict:
        """All raw entries for one provider — exact-id keyed, copied."""
        loaded = self._load()
        if not loaded:
            return {}
        provider = loaded[1].get(catalog_provider_id)
        if not isinstance(provider, dict):
            return {}
        models = provider.get("models")
        return deepcopy(models) if isinstance(models, dict) else {}

    def status(self) -> dict:
        loaded = self._load()
        active = self._active()
        error = self._last_error()
        bundled_manifest = self._bundled_manifest()
        bundled_payload = self._verified_bundle()
        bundled_ok = bundled_payload is not None
        refreshed = bool(loaded and active and loaded[0] == active["sha256"])
        manifest = active if refreshed else bundled_manifest
        fetched_at = (manifest or {}).get("fetched_at")
        stale = None
        if fetched_at:
            try:
                observed = datetime.fromisoformat(fetched_at)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=UTC)
                stale = (datetime.now(UTC) - observed).total_seconds() >= CATALOG_REFRESH_SECONDS
            except (TypeError, ValueError):
                fetched_at = None
        local_error = None
        if self._active_file.exists() and not refreshed:
            local_error = (
                "Stored catalog is invalid; using the bundled snapshot."
                if bundled_ok
                else "No valid local catalog snapshot is available."
            )
        return {
            "available": loaded is not None,
            "source": "refreshed" if refreshed else ("bundled" if bundled_ok else "none"),
            "revision": loaded[0] if loaded else None,
            "bundled_sha256": bundled_payload[0] if bundled_payload else None,
            "fetched_at": fetched_at,
            "stale": stale,
            "refresh_in_progress": self._refresh_task is not None and not self._refresh_task.done(),
            "last_error": local_error or (error or {}).get("error"),
            "last_error_at": (error or {}).get("at"),
            "bundled": bundled_ok,
        }

    # -- refresh -----------------------------------------------------------

    async def refresh(self, fetcher: Fetcher | None = None) -> dict:
        """One deduplicated refresh job. Callers share the task — a
        cancelled waiter never cancels the underlying job."""
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh(fetcher))
        try:
            return await asyncio.shield(self._refresh_task)
        except asyncio.CancelledError:
            # Waiter went away; the shared job keeps running.
            return {"ok": False, "error": "waiter cancelled", **self.status()}

    def schedule_refresh(self, fetcher: Fetcher | None = None) -> None:
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh(fetcher))

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except (asyncio.CancelledError, Exception):
                pass
            self._refresh_task = None

    async def _refresh(self, fetcher: Fetcher | None) -> dict:
        fetch = fetcher or _default_fetcher
        try:
            body = await fetch()
        except Exception as exc:
            code = _bounded_error(exc)
            logger.warning("model catalog fetch failed: %s", code)
            self._record_error(code)
            return {"ok": False, "error": code, **self.status()}

        try:
            decode_catalog(body)
        except ValueError as exc:
            self._record_error(_bounded_error(exc))
            return {"ok": False, "error": _bounded_error(exc), **self.status()}

        sha = _sha256(body)
        manifest = {
            "sha256": sha,
            "source": CATALOG_URL,
            "fetched_at": _utcnow_iso(),
            "size": len(body),
        }
        try:
            self._snapshots_dir.mkdir(parents=True, exist_ok=True)
            target = self._snapshots_dir / f"{sha}.json"
            if self._decode_path(target) is None or _sha256(target.read_bytes()) != sha:
                _atomic_write(target, body)
            _atomic_write(self._active_file, json.dumps(manifest, indent=1).encode())
        except OSError as exc:
            self._record_error(_bounded_error(exc))
            return {"ok": False, "error": _bounded_error(exc), **self.status()}
        try:
            _atomic_write(self._error_file, json.dumps({"error": None, "at": None}).encode())
        except OSError:
            logger.debug("could not clear catalog error status")
        return {"ok": True, "revision": sha, **self.status()}

    def _record_error(self, error: str) -> None:
        """Persist the failure separately — the active pointer (or the
        bundled fallback) still serves the last-known-good payload."""
        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                self._error_file,
                json.dumps({"error": error, "at": _utcnow_iso()}, indent=1).encode(),
            )
        except OSError:
            logger.debug("could not persist catalog error state", exc_info=True)


async def _default_fetcher() -> bytes:
    """Bounded HTTPS fetch — manual redirect loop so an off-origin hop is
    rejected before any request to it is made; streamed body capped at
    the size limit under a single total deadline."""
    import httpx

    url = CATALOG_URL

    async def _go() -> bytes:
        nonlocal url
        async with httpx.AsyncClient(
            verify=SSL_CERT_PATH or True, timeout=CATALOG_FETCH_TIMEOUT
        ) as client:
            for _ in range(CATALOG_MAX_REDIRECTS + 1):
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError("catalog URL is not a valid HTTPS origin")
                if (
                    urlsplit(CATALOG_URL).hostname != parsed.hostname
                    or parsed.port not in (None, 443)
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("catalog redirect left upstream origin")
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json"},
                    follow_redirects=False,
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise ValueError("redirect without location")
                        url = str(httpx.URL(url).join(location))
                        continue
                    resp.raise_for_status()
                    chunks = bytearray()
                    async for chunk in resp.aiter_bytes():
                        chunks += chunk
                        if len(chunks) > CATALOG_MAX_BYTES:
                            raise ValueError("catalog snapshot exceeds size cap")
                    return bytes(chunks)
        return b""

    return await asyncio.wait_for(_go(), timeout=CATALOG_FETCH_TIMEOUT)


# -- process-wide singleton + refresh worker ----------------------------

_snapshot: CatalogSnapshot | None = None


def get_catalog_snapshot() -> CatalogSnapshot:
    """The process catalog snapshot, rooted under the data dir."""
    global _snapshot
    if _snapshot is None:
        from ..config import settings

        _snapshot = CatalogSnapshot(store_dir=settings.db_path.parent / "model-catalog")
    return _snapshot


def reset_catalog_snapshot() -> None:
    """Test hook — drop the singleton so a new store_dir applies."""
    global _snapshot
    _snapshot = None


async def catalog_refresh_loop() -> None:
    """Refresh local catalog metadata daily and once at startup if overdue.

    Explicit opt-outs skip catalog downloads; bundled and last-known-good
    snapshots remain usable offline. Provider discovery has its own cadence.
    """
    from ..config import settings
    from .model_catalog import PROVIDER_DISCOVERY_SECONDS, schedule_provider_refresh

    snapshot = get_catalog_snapshot()
    last_attempt = 0.0
    last_provider_tick = 0.0
    overdue_done = False
    while True:
        enabled = getattr(settings, "model_catalog_auto_refresh", False)
        now = time.monotonic()
        if enabled:
            last_at = snapshot._active() or {}
            fetched = last_at.get("fetched_at")
            overdue = not overdue_done
            stale = True
            if fetched:
                try:
                    age = (datetime.now(UTC) - datetime.fromisoformat(fetched)).total_seconds()
                    stale = age >= CATALOG_REFRESH_SECONDS
                except Exception:
                    stale = True
            due = now - last_attempt >= CATALOG_REFRESH_SECONDS
            backoff = now - last_attempt >= CATALOG_RETRY_SECONDS
            if (overdue and stale) or (due and stale and backoff):
                overdue_done = True
                last_attempt = now
                try:
                    await snapshot.refresh()
                except Exception:
                    logger.exception("catalog auto-refresh failed")
        if now - last_provider_tick >= PROVIDER_DISCOVERY_SECONDS:
            last_provider_tick = now
            try:
                from sqlalchemy import select

                from ..db import async_session_factory
                from ..models.provider import Provider

                async with async_session_factory() as db:
                    result = await db.execute(select(Provider.id))
                    for (pid,) in result.all():
                        schedule_provider_refresh(pid)
            except Exception:
                logger.debug("provider discovery tick failed", exc_info=True)
        await asyncio.sleep(CATALOG_POLL_SECONDS)


_catalog_task: asyncio.Task | None = None


def start_catalog_worker() -> asyncio.Task:
    global _catalog_task
    if _catalog_task is None or _catalog_task.done():
        _catalog_task = asyncio.create_task(catalog_refresh_loop())
    return _catalog_task


async def stop_catalog_worker() -> None:
    global _catalog_task
    if _catalog_task is not None:
        _catalog_task.cancel()
        try:
            await _catalog_task
        except asyncio.CancelledError:
            pass
        _catalog_task = None
    # Join the shared refresh job and any provider discovery jobs.
    await get_catalog_snapshot().stop()
    try:
        from .model_catalog import stop_all_provider_jobs

        await stop_all_provider_jobs()
    except Exception:
        logger.debug("provider job shutdown failed", exc_info=True)
