"""Managed runtime installer — plan → consent → download → verify → activate.

Trust sources: lead-owned `runtime-install-policy.json` (bounds/hosts) and
`runtime-recipes.json` (publisher URLs + SHA-256 checksums — checksums, not
signatures). Everything mutable lives under
`settings.db_path.parent/"managed-runtimes"`; jobs never touch the caller's
system PATH and never execute anything not health-verified first.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import settings
from .dependencies import RuntimeDependencyRegistry
from .redaction import redact_text

log = logging.getLogger("agentos.runtime_installer")

_POLICY_PATH = Path(__file__).parent / "defaults" / "runtime-install-policy.json"
_RECIPES_PATH = Path(__file__).parent / "defaults" / "runtime-recipes.json"
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
_WIN_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_STATES_ACTIVE = {"queued", "downloading", "extracting", "verifying", "activating"}
_STATES_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}

Runner = Callable[..., Awaitable[tuple[int, bytes, bytes]]]


def utcnow() -> datetime:
    """Module-level clock seam — tests monkeypatch this, never the plan."""
    return datetime.now(UTC)


def _load_policy() -> dict:
    return json.loads(_POLICY_PATH.read_text())


def _load_recipes(recipes: dict | None = None) -> dict:
    """Normalize the bundled envelope ({schema_version, recipes:{...}}) or a
    bare test mapping into {dep_id: recipe}."""
    raw = recipes if recipes is not None else json.loads(_RECIPES_PATH.read_text())
    if "recipes" in raw and isinstance(raw["recipes"], dict):
        raw = raw["recipes"]
    return raw


def _bundle_bytes(recipes: dict | None = None) -> bytes:
    return json.dumps(_load_recipes(recipes), sort_keys=True, separators=(",", ":")).encode()


class PlanError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class _CancelRequested(Exception):
    pass


class _HealthFailed(Exception):
    pass


def _bounded(text: str, limit: int = 255) -> str:
    text, _, _ = redact_text(str(text), limit)
    return text or ""


def _first_version(text: str) -> str | None:
    m = _VERSION_RE.search(text)
    return m.group(1) if m else None


def _label(dep_id: str) -> str:
    return {"nodejs": "Node.js", "uv": "uv", "git": "Git"}.get(dep_id, dep_id)


def _unlocks(dep_id: str) -> str:
    return {
        "nodejs": "Local MCP servers (stdio)",
        "uv": "Python MCP servers and tools",
        "git": "Git MCP servers and workspace tooling",
    }.get(dep_id, "")


def _inside(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except (OSError, RuntimeError):
        return False


def _is_exec(path: Path, windows: bool) -> bool:
    if not path.is_file():
        return False
    if windows:
        return path.suffix.lower() in (".exe", ".cmd", ".bat", "")
    return os.access(path, os.X_OK)


class RuntimeInstaller:
    def __init__(
        self,
        *,
        registry: RuntimeDependencyRegistry,
        data_dir: Path,
        download: Callable[..., Awaitable[tuple[int, str]]] | None = None,
        health_runner: Runner | None = None,
        platform_key: str | None = None,
        recipes: dict | None = None,
        http_transport: Any | None = None,
    ) -> None:
        self._root = Path(data_dir)
        self._registry = registry
        self._policy = _load_policy()
        self._platform_key = platform_key
        self._download = download
        self._health_runner = health_runner
        self._recipes_injected = recipes
        self._http_transport = http_transport
        self._plans: dict[str, dict] = {}
        self._jobs: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._dep_locks: dict[str, asyncio.Lock] = {}
        self._plans_lock = threading.Lock()
        self._shutdown = False
        self._reconcile_jobs()

    # -- helpers --------------------------------------------------------------

    def _recipes(self) -> dict:
        return _load_recipes(self._recipes_injected)

    def _bundle_hash(self) -> str:
        return hashlib.sha256(_bundle_bytes(self._recipes_injected)).hexdigest()

    def _platform(self) -> str | None:
        return self._platform_key or getattr(self._registry, "_platform_key", None)

    def _is_windows(self) -> bool:
        return (self._platform() or "").startswith("windows")

    # -- job persistence -------------------------------------------------------

    @property
    def _jobs_dir(self) -> Path:
        return self._owned_path("jobs")

    def _job_path(self, job_id: str) -> Path:
        if not _JOB_ID_RE.match(job_id):
            raise PlanError(404, "job not found")
        return self._jobs_dir / f"{job_id}.json"

    @staticmethod
    def _finalize_cancelled_dependencies(job: dict) -> None:
        """On a cancelled job, pending rows get truthful terminal states:
        the in-flight dependency is 'cancelled', later ones 'not_started'.
        Reused/completed/failed rows are preserved."""
        current = job.get("current_dep")
        for row in job.get("dependencies", []):
            if row.get("status") == "pending":
                row["status"] = "cancelled" if row["id"] == current else "not_started"

    def _write_job(self, job: dict) -> None:
        """Atomic bounded job file — refuses to persist over the cap."""
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        cap = self._policy["max_job_file_bytes"]

        def dump(j: dict) -> bytes:
            return json.dumps(j, default=str).encode()

        payload = dump(job)
        if len(payload) > cap:
            job = dict(job)
            logs = list(job.get("log") or [])
            while logs and len(dump(job)) > cap:
                logs = logs[: max(0, len(logs) - 5)]
                job["log"] = logs
            payload = dump(job)
            if len(payload) > cap:
                raise PlanError(409, "job metadata exceeds the bounded file size")
        fd, tmp = tempfile.mkstemp(dir=self._jobs_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._job_path(job["id"]))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _read_job_file(self, path: Path) -> dict | None:
        """Bounded read + schema sanity — disk is not trusted input."""
        try:
            with open(path, "rb") as fh:
                raw = fh.read(self._policy["max_job_file_bytes"] + 1)
            if len(raw) > self._policy["max_job_file_bytes"]:
                return None
            job = json.loads(raw)
        except Exception:
            return None
        if not isinstance(job, dict):
            return None
        if (
            not _JOB_ID_RE.match(str(job.get("id", "")))
            or not isinstance(job.get("operator_id"), str)
            or job.get("state") not in (_STATES_ACTIVE | _STATES_TERMINAL | {"cancelling"})
            or not isinstance(job.get("dependencies"), list)
        ):
            return None
        allowed = set(self._policy["managed_dependencies"])
        if any(not isinstance(d, dict) or d.get("id") not in allowed for d in job["dependencies"]):
            return None
        return job

    def _load_job(self, job_id: str) -> dict | None:
        path = self._job_path(job_id)
        if not path.is_file():
            return None
        return self._read_job_file(path)

    def _reconcile_jobs(self) -> None:
        """Startup reconcile: non-terminal persisted jobs → interrupted, or
        completed when every planned dep's pointer already committed for
        this job. 'reuse' deps need no pointer."""
        try:
            jobs_dir = self._jobs_dir
        except PlanError:
            return
        if not jobs_dir.is_dir():
            return
        for path in sorted(jobs_dir.glob("*.json")):
            job = self._read_job_file(path)
            if job is None or job["state"] not in _STATES_ACTIVE | {"cancelling"}:
                continue
            committed = 0
            planned_installs = 0
            for dep in job["dependencies"]:
                if dep.get("action") != "install":
                    continue
                planned_installs += 1
                try:
                    pointer = self._owned_path(f"{dep['id']}/active.json")
                    with pointer.open("rb") as fh:
                        raw = fh.read(self._policy["max_job_file_bytes"] + 1)
                    if len(raw) > self._policy["max_job_file_bytes"]:
                        continue
                    pdata = json.loads(raw)
                    if pdata.get("job_id") == job["id"]:
                        committed += 1
                except Exception:
                    pass
            if planned_installs and committed == planned_installs:
                job["state"] = "completed"
                job["completed_at"] = utcnow().isoformat()
            else:
                job["state"] = "interrupted"
                if committed:
                    job["detail"] = f"interrupted with {committed} activated"
            self._write_job(job)

    def _stage_clean_root(self, dep_id: str, dest_rel: Path) -> Path:
        dep_root = self._owned_path(dep_id)
        dest = self._owned_path(f"{dep_id}/{dest_rel.as_posix()}")
        if not _inside(dest, dep_root):
            raise PlanError(409, "destination escapes the dependency root")
        return dest

    def _owned_path(self, relative: str) -> Path:
        """Resolve a path inside the immutable configured root —
        rejects symlink escapes BEFORE any mkdir/open/remove."""
        base = self._root.resolve()
        resolved = (base / relative).resolve()
        if not _inside(resolved, base):
            raise PlanError(409, "path escapes the managed store")
        return resolved

    # -- plan -------------------------------------------------------------------

    async def plan(self, dependency_ids: list[str], operator_id: str) -> dict:
        """Frozen immutable blueprint — no downloads, no fs writes."""
        if self._shutdown:
            raise PlanError(409, "installer is shutting down")
        allowed = set(self._policy["managed_dependencies"])
        if len(dependency_ids) != len(set(dependency_ids)):
            raise PlanError(422, "duplicate dependency ids")
        ids = list(dependency_ids)
        if not ids or len(ids) > self._policy["max_plan_dependencies"]:
            raise PlanError(422, "1-3 dependencies per plan")
        bad = [d for d in ids if d not in allowed]
        if bad:
            raise PlanError(400, f"unsupported dependencies: {', '.join(bad)}")

        recipes = self._recipes()
        bundle_sha = hashlib.sha256(
            json.dumps(recipes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        platform = self._platform()
        root = self._root.resolve()
        rows = await self._registry.status(force=True)
        ready = {r["id"]: r for r in rows}

        deps_public: list[dict] = []
        deps_internal: list[dict] = []
        total_bytes: int | None = 0
        plan_id = uuid.uuid4().hex
        for dep_id in ids:
            recipe = recipes.get(dep_id)
            if recipe is None:
                raise PlanError(400, f"no recipe for {dep_id}")
            if platform is None or platform not in recipe.get("platforms", {}):
                raise PlanError(409, f"no managed {dep_id} build for this platform")
            plat = recipe["platforms"][platform]
            existing = ready.get(dep_id, {})
            if existing.get("source") == "override":
                # A bad explicit override must not be silently replaced —
                # the operator opted into that path on purpose.
                raise PlanError(
                    409,
                    f"{dep_id} is pinned by an explicit override — "
                    "clear it in runtime settings first",
                )
            if existing.get("status") == "ready":
                row = {
                    "id": dep_id,
                    "label": _label(dep_id),
                    "action": "reuse",
                    "version": existing.get("version"),
                    "publisher": None,
                    "license": recipe.get("license"),
                    "verification": recipe.get("verification"),
                    "download_url": None,
                    "metadata_url": recipe.get("metadata_url"),
                    "sha256": None,
                    "download_bytes": None,
                    "destination": None,
                    "unlocks": _unlocks(dep_id),
                }
                deps_public.append(row)
                deps_internal.append(
                    {"id": dep_id, "action": "reuse", "version": existing.get("version")}
                )
                continue
            self._validate_url(plat["url"])
            sha = plat.get("sha256") or ""
            if not _SHA_RE.match(sha):
                raise PlanError(409, f"recipe for {dep_id} has no valid checksum")
            size = plat.get("download_bytes")
            if size is None:
                total_bytes = None
            elif total_bytes is not None:
                total_bytes += size
            rel_dest = Path("versions") / f"{recipe['version']}-{sha[:12]}-{plan_id[:8]}"
            abs_dest = root / dep_id / rel_dest
            deps_public.append(
                {
                    "id": dep_id,
                    "label": _label(dep_id),
                    "action": "install",
                    "version": recipe["version"],
                    "publisher": recipe["publisher"],
                    "license": recipe.get("license"),
                    "verification": recipe.get("verification"),
                    "download_url": plat["url"],
                    "metadata_url": recipe.get("metadata_url"),
                    "sha256": sha,
                    "download_bytes": size,
                    "destination": str(abs_dest),
                    "unlocks": _unlocks(dep_id),
                }
            )
            # Frozen execution spec — the worker never re-reads the file.
            deps_internal.append(
                {
                    "id": dep_id,
                    "action": "install",
                    "version": recipe["version"],
                    "rel_destination": rel_dest.as_posix(),
                    "recipe": json.loads(json.dumps(recipe)),
                    "platform_recipe": json.loads(json.dumps(plat)),
                }
            )

        public_plan = {
            "id": plan_id,
            "expires_at": (
                utcnow() + timedelta(seconds=self._policy["plan_ttl_seconds"])
            ).isoformat(),
            "platform": platform,
            "dependencies": deps_public,
            "total_download_bytes": total_bytes,
        }
        internal = {
            "operator_id": operator_id,
            "platform": platform,
            "root": str(root),
            "recipe_sha256": bundle_sha,
            "expires_at": public_plan["expires_at"],
            "deps": deps_internal,
            "job_id": None,
            "public_plan": json.loads(json.dumps(public_plan)),
        }
        with self._plans_lock:
            now = utcnow()
            self._plans = {
                k: v
                for k, v in self._plans.items()
                if datetime.fromisoformat(v["expires_at"]) > now
            }
            self._plans[plan_id] = internal
        return public_plan

    # -- start -------------------------------------------------------------------

    async def start(self, plan_id: str, operator_id: str, consent: bool) -> dict:
        if consent is not True:
            raise PlanError(422, "explicit consent required")
        internal = self._plans.get(plan_id)
        if internal is None:
            raise PlanError(404, "plan not found")
        if internal["operator_id"] != operator_id:
            raise PlanError(404, "plan not found")
        if internal["job_id"]:
            job = self._load_job(internal["job_id"])
            if job:
                return job
        if datetime.fromisoformat(internal["expires_at"]) <= utcnow():
            raise PlanError(409, "plan expired — request a fresh review")
        if self._bundle_hash() != internal["recipe_sha256"]:
            raise PlanError(409, "recipes changed — request a fresh review")
        if (
            str(self._root.resolve()) != internal["root"]
            or self._platform() != internal["platform"]
        ):
            raise PlanError(409, "environment changed — request a fresh review")
        installs = [d for d in internal["deps"] if d["action"] == "install"]
        for dep in installs:
            lock = self._dep_locks.setdefault(dep["id"], asyncio.Lock())
            if lock.locked():
                raise PlanError(409, f"another install is running for {dep['id']}")

        job = {
            "id": uuid.uuid4().hex,
            "plan_id": plan_id,
            "operator_id": operator_id,
            "state": "queued",
            "progress_bytes": 0,
            "current_dep": None,
            "created_at": utcnow().isoformat(),
            "plan": internal.get("public_plan"),
            "dependencies": [
                {
                    "id": d["id"],
                    "action": d["action"],
                    "version": d["version"],
                    "status": "pending",
                    "detail": None,
                }
                for d in internal["deps"]
            ],
            "log": [],
        }
        internal["job_id"] = job["id"]
        self._write_job(job)
        # Reservation + cancel event BEFORE the worker exists — a queued
        # cancel still resolves deterministically via the done callback.
        for dep in installs:
            await self._dep_locks[dep["id"]].acquire()
        self._cancel_events[job["id"]] = threading.Event()
        task = asyncio.create_task(self._run_job(job, internal))
        task.add_done_callback(lambda t, j=job["id"]: self._job_done(j))
        self._jobs[job["id"]] = task
        return job

    def _job_done(self, job_id: str) -> None:
        """Terminal bookkeeping — releases locks even if the task was
        cancelled before its first await."""
        job = self._load_job(job_id)
        deps = job["dependencies"] if job else []
        for dep in deps:
            if dep.get("action") == "install":
                lock = self._dep_locks.get(dep["id"])
                if lock and lock.locked():
                    lock.release()
        self._cancel_events.pop(job_id, None)
        if job and job["state"] in _STATES_ACTIVE | {"cancelling"}:
            job["state"] = "cancelled" if job["state"] == "cancelling" else "interrupted"
            if job["state"] == "cancelled":
                self._finalize_cancelled_dependencies(job)
            job["completed_at"] = utcnow().isoformat()
            self._write_job(job)

    async def _run_job(self, job: dict, internal: dict) -> None:
        cancel = self._cancel_events[job["id"]]
        any_failed = False
        try:
            for dep_spec in internal["deps"]:
                dep_id = dep_spec["id"]
                dep_row = next(d for d in job["dependencies"] if d["id"] == dep_id)
                if cancel.is_set():
                    dep_row["status"] = (
                        dep_row["status"] if dep_row["status"] != "pending" else "not_started"
                    )
                    raise _CancelRequested()
                if any_failed:
                    dep_row["status"] = "not_started"
                    continue
                if dep_spec["action"] == "reuse":
                    dep_row["status"] = "reused"
                    dep_row["detail"] = "existing installation selected"
                    continue
                job["current_dep"] = dep_id
                try:
                    await self._install_one(job, dep_spec, internal, cancel)
                    dep_row["status"] = "completed"
                except _CancelRequested:
                    dep_row["status"] = "cancelled"
                    raise
                except Exception as exc:
                    dep_row["status"] = "failed"
                    dep_row["detail"] = _bounded(str(exc))
                    job["state"] = "failed"
                    self._job_log(job, f"{dep_id} failed: {type(exc).__name__}")
                    any_failed = True
            if job["state"] == "failed":
                pass
            elif job["state"] == "cancelling":
                raise _CancelRequested()
            else:
                job["state"] = "completed"
            job["completed_at"] = utcnow().isoformat()
        except _CancelRequested:
            job["state"] = "cancelled"
            job["completed_at"] = utcnow().isoformat()
        except asyncio.CancelledError:
            job["state"] = "cancelled"
            job["completed_at"] = utcnow().isoformat()
            raise
        except Exception as exc:
            job["state"] = "failed"
            job["completed_at"] = utcnow().isoformat()
            self._job_log(job, f"job failed: {type(exc).__name__}")
        finally:
            if job["state"] == "cancelled":
                self._finalize_cancelled_dependencies(job)
            self._write_job(job)
            self._registry.clear_cache()
            try:
                await self._registry.status(force=True)
            except Exception:
                pass

    async def _install_one(
        self, job: dict, dep_spec: dict, internal: dict, cancel: threading.Event
    ) -> None:
        dep_id = dep_spec["id"]
        stage = self._owned_path(f".staging/{job['id']}/{dep_id}")
        payload = stage / "payload"
        dest = self._stage_clean_root(dep_id, Path(dep_spec["rel_destination"]))
        try:
            job["state"] = "downloading"
            self._write_job(job)
            archive = await self._fetch(dep_spec, stage / "download", job, cancel)
            self._check_cancel(cancel)
            job["state"] = "extracting"
            self._write_job(job)
            # Shield the thread so task cancellation cannot orphan it; the
            # threading event stops the worker, which we then await.
            extract_task = asyncio.create_task(
                asyncio.to_thread(
                    self._extract, archive, payload, dep_spec["platform_recipe"], cancel
                )
            )
            try:
                await asyncio.shield(extract_task)
            except asyncio.CancelledError:
                cancel.set()
                await extract_task
                raise
            self._check_cancel(cancel)
            job["state"] = "verifying"
            self._write_job(job)
            ok = await self._health(dep_id, dep_spec, payload)
            if not ok:
                raise _HealthFailed(f"{dep_id} health check failed")
            self._check_cancel(cancel)
            job["state"] = "activating"
            self._write_job(job)
            self._activate(job, dep_spec, payload, dest, dep_id, cancel)
        finally:
            import shutil

            shutil.rmtree(stage, ignore_errors=True)

    def _check_cancel(self, cancel: threading.Event) -> None:
        if cancel.is_set():
            raise _CancelRequested()

    def _job_log(self, job: dict, text: str) -> None:
        logs = job.setdefault("log", [])
        entry = self._policy["max_job_log_entry_characters"]
        logs.append({"at": utcnow().isoformat(), "text": _bounded(text, entry)})
        del logs[: max(0, len(logs) - self._policy["max_job_log_entries"])]

    # -- download ----------------------------------------------------------------

    async def _fetch(
        self, dep_spec: dict, dest_dir: Path, job: dict, cancel: threading.Event
    ) -> Path:
        plat = dep_spec["platform_recipe"]
        url = plat["url"]
        expected_sha = plat["sha256"]
        if self._download is not None:
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / "archive"
            bytes_done, sha = await self._download(url, target, job, cancel)
            if not hmac.compare_digest(str(sha), expected_sha):
                raise PlanError(409, "downloaded bytes do not match the recipe checksum")
            job["progress_bytes"] += int(bytes_done)
            self._write_job(job)
            return target

        import httpx

        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "archive"
        deadline = self._policy["download_deadline_seconds"]
        max_bytes = self._policy["max_download_bytes"]
        progress_interval = self._policy["progress_write_interval_seconds"]
        last_persist = 0.0
        redirects = 0
        hasher = hashlib.sha256()
        total = 0

        async with asyncio.timeout(deadline):
            while True:
                if redirects > self._policy["max_redirects"]:
                    raise PlanError(409, "too many redirects")
                self._validate_url(url)
                timeout = httpx.Timeout(
                    connect=self._policy["connect_timeout_seconds"],
                    read=self._policy["read_timeout_seconds"],
                    write=30.0,
                    pool=30.0,
                )
                try:
                    async with httpx.AsyncClient(
                        timeout=timeout,
                        follow_redirects=False,
                        verify=True,
                        transport=self._http_transport,
                    ) as client:
                        async with client.stream("GET", url) as response:
                            if response.is_redirect:
                                url = str(response.url.join(response.headers["location"]))
                                redirects += 1
                                continue
                            response.raise_for_status()
                            declared = response.headers.get("content-length")
                            if declared and int(declared) > max_bytes:
                                raise PlanError(409, "download exceeds the policy cap")
                            with open(target, "wb") as fh:
                                async for chunk in response.aiter_bytes(65536):
                                    if cancel.is_set():
                                        raise _CancelRequested()
                                    total += len(chunk)
                                    if total > max_bytes:
                                        raise PlanError(409, "download exceeds the policy cap")
                                    hasher.update(chunk)
                                    fh.write(chunk)
                                    job["progress_bytes"] += len(chunk)
                                    if time.monotonic() - last_persist >= progress_interval:
                                        self._write_job(job)
                                        last_persist = time.monotonic()
                            break
                except PlanError:
                    raise
                except Exception as exc:
                    # Category-only — never persist raw URLs or SDK payloads.
                    raise PlanError(409, f"download failed: {type(exc).__name__}") from None
        actual = hasher.hexdigest()
        if not hmac.compare_digest(actual, expected_sha):
            raise PlanError(409, "downloaded bytes do not match the recipe checksum")
        self._job_log(job, f"{dep_spec['id']} downloaded {total} bytes, sha256 ok")
        return target

    def _validate_url(self, url: str) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise PlanError(409, "download must be HTTPS")
        if parsed.username or parsed.password:
            raise PlanError(409, "download URL must not embed credentials")
        if parsed.port not in (None, 443):
            raise PlanError(409, "non-default download ports are not allowed")
        host = (parsed.hostname or "").lower()
        if host not in set(self._policy["download_hosts"]):
            raise PlanError(409, f"download host '{host}' is not allowed")

    # -- archive extraction --------------------------------------------------------

    def _extract(self, archive: Path, payload: Path, plat: dict, cancel: threading.Event) -> None:
        """Two-phase safe extraction: validate every header and the link
        graph BEFORE any byte is written; create links only after regular
        files exist."""
        payload.mkdir(parents=True, exist_ok=True)
        fmt = plat["archive_format"]
        if fmt == "tar.gz":
            self._extract_tar(archive, payload, cancel)
        elif fmt == "zip":
            self._extract_zip(archive, payload, cancel)
        else:
            raise PlanError(409, f"unsupported archive format {fmt}")
        self._select_root(payload, plat)

    def _select_root(self, stage: Path, plat: dict) -> None:
        """Lift the declared archive root so executables sit at stage/."""
        for root in plat.get("roots") or ["."]:
            base = stage / root
            if all((base / rel).is_file() for rel in plat["executables"].values()):
                if root != ".":
                    import shutil

                    for item in base.iterdir():
                        shutil.move(str(item), stage / item.name)
                    base.rmdir()
                return
        raise PlanError(409, "archive missing the declared executable root")

    def _validate_member_name(self, name: str, folded: set[str]) -> str:
        if not name or "\x00" in name:
            raise PlanError(409, "invalid archive member")
        if name.startswith(("/", "\\")):
            raise PlanError(409, "absolute archive member rejected")
        parts = name.split("/")
        for part in parts:
            if part in ("", ".", ".."):
                if part == "..":
                    raise PlanError(409, "path traversal member rejected")
                continue
            if "\\" in part:
                raise PlanError(409, "backslash path component rejected")
            if ":" in part:
                raise PlanError(409, "colon in member name rejected")
            stripped = part.rstrip(" .")
            if not stripped or stripped.lower() in _WIN_RESERVED:
                raise PlanError(409, "reserved member name rejected")
        normalized = "/".join(p for p in parts if p not in ("", "."))
        if normalized.casefold() in folded:
            raise PlanError(409, "duplicate archive member rejected")
        return normalized

    def _link_target_ok(self, stage: Path, name: str, target: str, hard: bool) -> Path:
        """Link target must resolve inside the stage — '../' components are
        legal while the RESOLVED path stays contained."""
        if not target or "\x00" in target or len(target.encode("utf-8", "replace")) > 4096:
            raise PlanError(409, "link target invalid")
        base = stage if hard else stage / Path(name).parent
        resolved = (base / target).resolve()
        if not _inside(resolved, stage):
            raise PlanError(409, "link escapes the stage")
        return resolved

    def _resolve_link_chain(
        self, stage: Path, links: dict[str, tuple[str, bool]], name: str
    ) -> Path:
        """Follow a symlink chain — rejects cycles and depth > policy."""
        seen = set()
        current = name
        for _ in range(self._policy["max_link_depth"] + 1):
            entry = links.get(current)
            if entry is None:
                return (stage / current).resolve()
            target, hard = entry
            if current in seen:
                raise PlanError(409, "link cycle rejected")
            seen.add(current)
            current_parent = stage if hard else stage / Path(current).parent
            nxt = (current_parent / target).resolve()
            if not _inside(nxt, stage):
                raise PlanError(409, "link escapes the stage")
            current = str(nxt.relative_to(stage.resolve()))
        raise PlanError(409, "link depth exceeded")

    def _extract_tar(self, archive: Path, stage: Path, cancel: threading.Event) -> None:
        folded: set[str] = set()
        files: list[tuple] = []
        links: dict[str, tuple[str, bool]] = {}
        dirs: list[str] = []
        total = 0
        members = 0
        # Phase 1 — bounded header scan, nothing written yet.
        with tarfile.open(archive, "r:gz") as tf:
            while True:
                if cancel.is_set():
                    raise _CancelRequested()
                m = tf.next()
                if m is None:
                    break
                members += 1
                if members > self._policy["max_archive_members"]:
                    raise PlanError(409, "archive exceeds member limit")
                name = self._validate_member_name(m.name, folded)
                folded.add(name.casefold())
                if m.isdev() or m.isfifo() or m.issparse():
                    raise PlanError(409, "special member rejected")
                if m.issym() or m.islnk():
                    links[name] = (m.linkname, m.islnk())
                    continue
                if m.isdir():
                    dirs.append(name)
                    continue
                if not m.isfile():
                    raise PlanError(409, "unsupported member type")
                if m.size > self._policy["max_member_bytes"]:
                    raise PlanError(409, "member exceeds size limit")
                total += m.size
                if total > self._policy["max_extracted_bytes"]:
                    raise PlanError(409, "archive exceeds extracted size cap")
                files.append((m, name))
        # Phase 2 — validate the full link graph before ANY write.
        for link_name in links:
            self._resolve_link_chain(stage, links, link_name)
        # No regular file may live under a link path — writes would escape.
        link_prefixes = {n + "/" for n in links}
        for _, fname in files + [(None, d) for d in dirs]:
            if any(fname.startswith(p) for p in link_prefixes):
                raise PlanError(409, "member under a link path rejected")
        # Phase 3 — write dirs + files, then materialize links.
        for d in dirs:
            (stage / d).mkdir(parents=True, exist_ok=True)
        chunk = self._policy["io_chunk_bytes"]
        with tarfile.open(archive, "r:gz") as tf:
            wanted = {name for _, name in files}
            while True:
                if cancel.is_set():
                    raise _CancelRequested()
                m = tf.next()
                if m is None:
                    break
                # Normalize the raw name — publisher archives store './x'
                # entries; selection must use the SAME canonical key.
                try:
                    canon = self._validate_member_name(m.name, set())
                except PlanError:
                    continue  # rejected in phase 1 already
                if canon not in wanted:
                    continue
                dest = stage / canon
                dest.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                try:
                    with open(dest, "wb") as out:
                        while True:
                            if cancel.is_set():
                                raise _CancelRequested()
                            data = src.read(chunk)
                            if not data:
                                break
                            out.write(data)
                finally:
                    src.close()
                os.chmod(dest, 0o755 if (m.mode & 0o111) else 0o644)
        for link_name, (target, hard) in links.items():
            resolved = self._resolve_link_chain(stage, links, link_name)
            dst = stage / link_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() or dst.is_symlink():
                continue
            if hard:
                if not resolved.is_file():
                    raise PlanError(409, "hardlink to non-file rejected")
                os.link(resolved, dst)
            else:
                try:
                    os.symlink(target, dst)
                except OSError:
                    raise PlanError(409, "symlinks unsupported here") from None

    def _extract_zip(self, archive: Path, stage: Path, cancel: threading.Event) -> None:
        folded: set[str] = set()
        links: dict[str, tuple[str, bool]] = {}
        total = 0
        chunk = self._policy["io_chunk_bytes"]
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > self._policy["max_archive_members"]:
                raise PlanError(409, "archive exceeds member limit")
            entries = []
            for info in infos:
                if cancel.is_set():
                    raise _CancelRequested()
                name = self._validate_member_name(info.filename, folded)
                folded.add(name.casefold())
                mode_bits = (info.external_attr >> 16) & 0o170000
                if mode_bits == 0o120000:
                    if info.file_size > 4096:
                        raise PlanError(409, "link target too long")
                    # Bound the read — never unbounded decompression.
                    raw = zf.open(info).read(4097)
                    if len(raw) > 4096:
                        raise PlanError(409, "link target too long")
                    links[name] = (raw.decode("utf-8", "replace"), False)
                    continue
                if mode_bits not in (0, 0o100000) and not info.is_dir():
                    raise PlanError(409, "special member rejected")
                if info.is_dir():
                    entries.append((info, name, "dir"))
                    continue
                if info.file_size > self._policy["max_member_bytes"]:
                    raise PlanError(409, "member exceeds size limit")
                total += info.file_size
                if total > self._policy["max_extracted_bytes"]:
                    raise PlanError(409, "archive exceeds extracted size cap")
                entries.append((info, name, "file"))
            for link_name in links:
                self._resolve_link_chain(stage, links, link_name)
            link_prefixes = {n + "/" for n in links}
            for _, name, _ in entries:
                if any(name.startswith(p) for p in link_prefixes):
                    raise PlanError(409, "member under a link path rejected")
            for info, name, kind in entries:
                if cancel.is_set():
                    raise _CancelRequested()
                if kind == "dir":
                    (stage / name).mkdir(parents=True, exist_ok=True)
                    continue
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    while True:
                        if cancel.is_set():
                            raise _CancelRequested()
                        data = src.read(chunk)
                        if not data:
                            break
                        out.write(data)
                perm = (info.external_attr >> 16) & 0o111
                os.chmod(dest, 0o755 if perm else 0o644)
            for link_name, (target, _hard) in links.items():
                dst = stage / link_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() or dst.is_symlink():
                    continue
                try:
                    os.symlink(target, dst)
                except OSError:
                    raise PlanError(409, "symlinks unsupported here") from None

    # -- health ----------------------------------------------------------------------

    async def _health(self, dep_id: str, dep_spec: dict, payload: Path) -> bool:
        expected = dep_spec["recipe"].get("health_versions") or {}
        plat = dep_spec["platform_recipe"]
        runner = self._health_runner or self._registry_runner()
        executables = {cmd: str(payload / rel) for cmd, rel in plat["executables"].items()}
        env = self._health_env(executables, dep_id, payload)
        windows = self._is_windows()
        for cmd, want in expected.items():
            path = executables.get(cmd)
            if path is None or not _is_exec(Path(path), windows):
                return False
            argv = self._health_argv(cmd, path, executables, payload)
            if argv is None:
                return False
            try:
                code, out, _err = await runner(argv, env=env)
            except Exception:
                return False
            if code != 0:
                return False
            if _first_version(out.decode(errors="replace")) != want:
                return False
        return True

    def _health_argv(
        self, cmd: str, path: str, executables: dict, payload: Path
    ) -> list[str] | None:
        p = Path(path)
        if p.suffix.lower() in (".cmd", ".bat"):
            if cmd not in ("npm", "npx"):
                return None
            node = executables.get("node")
            if node is None or Path(node).parent != p.parent:
                return None
            script = p.parent / "node_modules" / "npm" / "bin" / f"{cmd}-cli.js"
            if not script.is_file() or not _inside(script, payload):
                return None
            return [node, str(script.resolve()), "--version"]
        return [path, "--version"]

    def _health_env(self, executables: dict, dep_id: str, payload: Path) -> dict:
        env = dict(os.environ)
        dirs = {str(Path(p).parent) for p in executables.values()}
        env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
        env["npm_config_update_notifier"] = "false"
        env["npm_config_audit"] = "false"
        env["npm_config_fund"] = "false"
        env["UV_NO_PROGRESS"] = "1"
        if dep_id == "git":
            libexec = payload / "libexec" / "git-core"
            if libexec.is_dir():
                env["GIT_EXEC_PATH"] = str(libexec)
        return env

    def _registry_runner(self):
        return getattr(self._registry, "_runner", None) or _default_runner

    # -- activation ---------------------------------------------------------------------

    def _activate(
        self,
        job: dict,
        dep_spec: dict,
        payload: Path,
        dest: Path,
        dep_id: str,
        cancel: threading.Event,
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise PlanError(409, "planned destination already exists")
        payload.rename(dest)
        self._check_cancel(cancel)
        # Pointer `directory` is relative to the DEP root; executables are
        # recipe-declared paths inside the activated version dir.
        pointer = {
            "version": dep_spec["version"],
            "platform": self._platform(),
            "directory": dep_spec["rel_destination"],
            "executables": dict(dep_spec["platform_recipe"]["executables"]),
            "job_id": job["id"],
            "download_url": dep_spec["platform_recipe"]["url"],
            "sha256": dep_spec["platform_recipe"]["sha256"],
            "verification": dep_spec["recipe"].get("verification"),
            "installed_at": utcnow().isoformat(),
            "health_versions": dep_spec["recipe"].get("health_versions"),
        }
        dep_root = self._owned_path(dep_id)
        dep_root.mkdir(parents=True, exist_ok=True)
        final = dep_root / "active.json"
        fd, tmp = tempfile.mkstemp(dir=dep_root, prefix="active-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(pointer, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- jobs API -------------------------------------------------------------------------

    def get_job(self, job_id: str, operator_id: str) -> dict:
        job = self._load_job(job_id)
        if job is None or job.get("operator_id") != operator_id:
            raise PlanError(404, "job not found")
        return job

    def list_jobs(self, operator_id: str, limit: int = 20) -> list[dict]:
        jobs = []
        if self._jobs_dir.is_dir():
            entries = []
            for path in self._jobs_dir.glob("*.json"):
                job = self._read_job_file(path)
                if job is not None and job.get("operator_id") == operator_id:
                    entries.append(job)
            entries.sort(key=lambda j: j.get("created_at", ""), reverse=True)
            jobs = entries[:limit]
        return jobs

    async def cancel(self, job_id: str, operator_id: str) -> dict:
        job = self.get_job(job_id, operator_id)
        if job["state"] in _STATES_TERMINAL | {"cancelling"}:
            return job
        job["state"] = "cancelling"
        self._write_job(job)
        event = self._cancel_events.get(job_id)
        if event is not None:
            event.set()
        task = self._jobs.get(job_id)
        if task and not task.done():
            task.cancel()
        return job

    async def shutdown(self) -> None:
        self._shutdown = True
        # Signal every cancel event first so in-flight threads stop.
        for event in self._cancel_events.values():
            event.set()
        tasks = [t for t in self._jobs.values() if not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:
                pass


async def _default_runner(argv, env):
    from .dependencies import _default_runner as runner

    return await runner(argv, env=env)


_INSTALLER: RuntimeInstaller | None = None


def get_runtime_installer() -> RuntimeInstaller:
    global _INSTALLER
    if _INSTALLER is None:
        from .dependencies import get_dependency_registry

        _INSTALLER = RuntimeInstaller(
            registry=get_dependency_registry(),
            data_dir=settings.db_path.parent / "managed-runtimes",
        )
    return _INSTALLER
