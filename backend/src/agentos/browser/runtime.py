"""Browser runtime: discovery + operator-driven install.

Resolution order for ``find_browser_binary``:

1. ``AGENTOS_BROWSER_BINARY`` / ``settings.browser_binary`` — the
   operator's explicit choice of any Chromium-family binary.
2. A Chromium-family browser already installed on the machine (Chrome,
   Edge, Brave, Chromium) — detected, never modified; every launch still
   gets our own ``--user-data-dir``.
3. The CaberOS-managed install under ``data/browser-runtime/`` — pinned,
   verified, installed only on operator request.
4. ``runtime_unavailable`` — callers report honestly, never silently install.

We deliberately do NOT scan other tools' caches (e.g. Playwright's) — a
binary we didn't install, can't pin, and don't control the lifecycle of is
not a dependency worth having.

Install path downloads the pinned Chrome for Testing build (the version the
W4 spike validated), verifies the downloaded zip's integrity, installs under
app data, and health-checks by launching ``--version``. Google does not
publish per-zip hashes; integrity = TLS-downloaded zip + recorded sha256 +
platform signature check (``codesign -v`` on macOS) + a real launch.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from ..config import settings

# Pinned approved artifact — the version the W4 spike exercised.
RUNTIME_VERSION = "145.0.7632.6"
_CFT_VERSIONS_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
)

# Live install status for the settings UI to poll — one install at a time.
# {phase: preparing|downloading|extracting|verifying, downloaded: int, total: int|None}
_install_progress: dict = {}


def runtime_root() -> Path:
    return (settings.db_path.parent / "browser-runtime").resolve()


def _platform_key() -> str | None:
    """Map this machine to a Chrome for Testing platform slug."""
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if machine == "arm64" else "mac-x64"
    if sys.platform.startswith("linux"):
        return "linux64" if machine in ("x86_64", "amd64") else None
    if sys.platform == "win32":
        return "win64" if machine in ("amd64", "x86_64") else "win32"
    return None


def _binary_in_install(root: Path, plat: str) -> Path | None:
    """Locate the main executable inside an extracted CfT zip."""
    if plat == "mac-arm64" or plat == "mac-x64":
        hits = sorted(root.glob("chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/*"))
    elif plat.startswith("win"):
        hits = sorted(root.glob("chrome-win*/chrome.exe"))
    else:
        hits = sorted(root.glob("chrome-linux*/chrome"))
    return hits[0] if hits and hits[0].is_file() else None


def _system_browser_candidates() -> list[tuple[str, Path]]:
    """Chromium-family browsers already installed on this machine, as
    (display name, binary path) pairs.

    Launched with our own --user-data-dir, so the operator's personal
    profile is never touched — detection only picks the binary."""
    if sys.platform == "darwin":
        apps = [
            ("Google Chrome", "Google Chrome.app", "Google Chrome"),
            ("Microsoft Edge", "Microsoft Edge.app", "Microsoft Edge"),
            ("Brave", "Brave Browser.app", "Brave Browser"),
            ("Chromium", "Chromium.app", "Chromium"),
        ]
        return [
            (name, Path(f"/Applications/{app}/Contents/MacOS/{exe}")) for name, app, exe in apps
        ]
    if sys.platform == "win32":
        candidates: list[tuple[str, Path]] = []
        for root in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if not root:
                continue
            r = Path(root)
            candidates += [
                ("Google Chrome", r / "Google/Chrome/Application/chrome.exe"),
                ("Microsoft Edge", r / "Microsoft/Edge/Application/msedge.exe"),
                ("Brave", r / "BraveSoftware/Brave-Browser/Application/brave.exe"),
                ("Chromium", r / "Chromium/Application/chrome.exe"),
            ]
        return candidates
    import shutil

    names = (
        ("Google Chrome", ("google-chrome", "google-chrome-stable")),
        ("Microsoft Edge", ("microsoft-edge", "microsoft-edge-stable")),
        ("Brave", ("brave-browser", "brave")),
        ("Chromium", ("chromium", "chromium-browser")),
    )
    out: list[tuple[str, Path]] = []
    for display, binaries in names:
        for n in binaries:
            if p := shutil.which(n):
                out.append((display, Path(p)))
                break
    return out


def detected_browsers() -> list[dict]:
    """Installed Chromium-family browsers, for the settings dropdown."""
    seen: set[str] = set()
    out: list[dict] = []
    for name, path in _system_browser_candidates():
        if path.is_file() and name not in seen:
            seen.add(name)
            out.append({"name": name, "path": str(path)})
    return out


def find_browser_binary() -> Path | None:
    """Locate a compatible Chromium-family binary, or None.

    Order: explicit operator override → browser already on this machine →
    CaberOS-managed pinned install."""
    override = os.environ.get("AGENTOS_BROWSER_BINARY") or settings.browser_binary
    if override:
        p = Path(override).expanduser().resolve()
        return p if p.is_file() else None

    for _, candidate in _system_browser_candidates():
        if candidate.is_file():
            return candidate

    plat = _platform_key()
    if plat:
        managed = _binary_in_install(runtime_root() / RUNTIME_VERSION, plat)
        if managed:
            return managed
    return None


async def _download(url: str, dest: Path) -> str:
    """Stream-download url to dest; returns the sha256 of what arrived."""
    import httpx

    digest = hashlib.sha256()
    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0) or None
            _install_progress.update({"phase": "downloading", "downloaded": 0, "total": total})
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(1 << 20):
                    digest.update(chunk)
                    f.write(chunk)
                    _install_progress["downloaded"] += len(chunk)
    return digest.hexdigest()


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract the CfT zip, recreating symlinks — ``zipfile.extractall``
    writes them as text files, which silently corrupts the .app bundle
    (launches, then crashes when a page actually loads)."""
    root = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                out = (dest_dir / info.filename).resolve()
                if not out.is_relative_to(root):
                    continue
                target = zf.read(info).decode()
                if Path(target).is_absolute():
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                out.unlink(missing_ok=True)
                out.symlink_to(target)
            else:
                extracted = Path(zf.extract(info, dest_dir))
                perm = mode & 0o7777
                if perm and extracted.is_file() and not extracted.is_symlink():
                    extracted.chmod(perm)


def _verify_signature(binary: Path, plat: str) -> str:
    """Best available signature check for the platform. Returns a note.

    CfT ships adhoc-signed (no Developer ID cert, no sealed resources), so
    ``codesign -v`` can never pass on it. What we can verify is that the
    Mach-O's embedded code-directory hash parses — the seal is self-
    consistent; real integrity is the recorded sha256 + health check."""
    if plat.startswith("mac"):
        proc = subprocess.run(["codesign", "-dvvv", str(binary)], capture_output=True, text=True)
        fields = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in proc.stderr.splitlines()
            if "=" in line
        }
        cdhash, sig = fields.get("CDHash"), fields.get("Signature")
        if proc.returncode == 0 and cdhash:
            return f"signature: {sig or 'unknown'} (cdhash {cdhash[:16]}…)"
        if proc.returncode == 0 and sig:
            return f"signature: {sig}"
        return f"signature: unreadable — {(proc.stderr or proc.stdout).strip()[:120]}"
    return "signature: not checked on this platform"


async def _health_check(binary: Path) -> str:
    """Prove the install actually browses — launch + CDP attach + a page,
    the same path runs use. ``--version`` alone passes on a corrupt
    bundle (it never loads the framework)."""
    from .cdp import BrowserSession

    prof = Path(tempfile.mkdtemp(prefix="agentos-cft-health-"))
    session = BrowserSession(binary, prof)
    try:
        await session.open("about:blank")
    finally:
        await session.close()
        shutil.rmtree(prof, ignore_errors=True)
    ver = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=15)
    return ver.stdout.strip()


async def install_runtime() -> dict:
    """Download + verify + install the pinned runtime under app data."""
    plat = _platform_key()
    if plat is None:
        return {
            "status": "unsupported_platform",
            "detail": f"{sys.platform}/{platform.machine()} has no pinned runtime build",
        }
    if _install_progress:
        return {"status": "error", "detail": "an install is already in progress"}

    import httpx

    _install_progress.update({"phase": "preparing", "downloaded": 0, "total": None})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_CFT_VERSIONS_URL)
            resp.raise_for_status()
            versions = resp.json()["versions"]
        entry = next((v for v in versions if v["version"] == RUNTIME_VERSION), None)
        if entry is None:
            return {"status": "error", "detail": f"pinned version {RUNTIME_VERSION} not published"}
        url = next(
            (d["url"] for d in entry["downloads"]["chrome"] if d["platform"] == plat),
            None,
        )
        if url is None:
            return {"status": "error", "detail": f"no {plat} build for {RUNTIME_VERSION}"}

        dest_dir = runtime_root() / RUNTIME_VERSION
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = Path(tmp.name)
        try:
            sha256 = await _download(url, zip_path)
            _install_progress.update({"phase": "extracting", "total": None})
            _extract_zip(zip_path, dest_dir)
            binary = _binary_in_install(dest_dir, plat)
            if binary is None:
                return {"status": "error", "detail": "archive extracted but no binary found"}
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            _install_progress.update({"phase": "verifying"})
            sig_note = _verify_signature(binary, plat)
            try:
                version_out = await _health_check(binary)
            except Exception as exc:
                shutil.rmtree(dest_dir, ignore_errors=True)
                return {"status": "error", "detail": f"health check failed: {exc}"}
            (dest_dir / "INSTALL.json").write_text(
                __import__("json").dumps(
                    {
                        "version": RUNTIME_VERSION,
                        "platform": plat,
                        "url": url,
                        "sha256": sha256,
                        "signature": sig_note,
                        "health": version_out,
                    },
                    indent=2,
                )
            )
            return {
                "status": "installed",
                "version": RUNTIME_VERSION,
                "binary": str(binary),
                "sha256": sha256,
                "signature": sig_note,
                "health": version_out,
            }
        finally:
            zip_path.unlink(missing_ok=True)
    finally:
        _install_progress.clear()


def remove_runtime() -> dict:
    root = runtime_root() / RUNTIME_VERSION
    if not root.exists():
        return {"status": "not_installed"}
    shutil.rmtree(root)
    return {"status": "removed", "version": RUNTIME_VERSION}


def _resolution_source(binary: Path) -> str:
    """How the resolved binary was picked: explicit operator override,
    auto-detected system browser, or the managed install."""
    override = os.environ.get("AGENTOS_BROWSER_BINARY") or settings.browser_binary
    if override and binary == Path(override).expanduser().resolve():
        return "override"
    if binary.is_relative_to((runtime_root() / RUNTIME_VERSION).resolve()):
        return "managed"
    return "system"


def runtime_status() -> dict:
    binary = find_browser_binary()
    managed = (runtime_root() / RUNTIME_VERSION).resolve()
    plat = _platform_key()
    managed_bin = _binary_in_install(managed, plat) if plat else None
    if binary is None:
        return {
            "status": "runtime_unavailable",
            "detail": (
                "No browser runtime found. CaberOS can install its own "
                "browser, or point it at a Chromium-family browser."
            ),
            "version": RUNTIME_VERSION,
            "installable": plat is not None,
            "managed_binary": str(managed_bin.resolve()) if managed_bin else None,
            "install_progress": dict(_install_progress) or None,
        }
    return {
        "status": "ok",
        "binary": str(binary),
        "managed": binary.is_relative_to(managed),
        "managed_binary": str(managed_bin.resolve()) if managed_bin else None,
        "source": _resolution_source(binary),
        "version": RUNTIME_VERSION,
        "install_progress": dict(_install_progress) or None,
    }
