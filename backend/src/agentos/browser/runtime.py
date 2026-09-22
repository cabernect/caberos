"""Managed browser runtime: discovery + first-use install.

Resolution order for ``find_browser_binary``:

1. ``AGENTOS_BROWSER_BINARY`` env override — explicit operator choice.
2. The CaberOS-managed install under ``data/browser-runtime/``.
3. Playwright-managed cache — a Chromium-family binary already present.
4. ``runtime_unavailable`` — callers report honestly, never silently install.

Install path downloads the pinned Chrome for Testing build (the version the
W4 spike validated), verifies the downloaded zip's integrity, installs under
app data, and health-checks by launching ``--version``. Google does not
publish per-zip hashes; integrity = TLS-downloaded zip + recorded sha256 +
platform signature check (``codesign -v`` on macOS) + a real launch.
"""

from __future__ import annotations

import asyncio
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


def runtime_root() -> Path:
    return settings.db_path.parent / "browser-runtime"


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


def _playwright_cache_roots() -> list[Path]:
    roots = []
    if custom := os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        roots.append(Path(custom))
    roots.append(Path.home() / "Library" / "Caches" / "ms-playwright")  # macOS
    roots.append(Path.home() / ".cache" / "ms-playwright")  # Linux
    return roots


def find_browser_binary() -> Path | None:
    """Locate a compatible Chromium-family binary, or None."""
    override = os.environ.get("AGENTOS_BROWSER_BINARY")
    if not override:
        from ..config import settings

        override = settings.browser_binary
    if override:
        p = Path(override).expanduser()
        return p if p.is_file() else None

    plat = _platform_key()
    if plat:
        managed = _binary_in_install(runtime_root() / RUNTIME_VERSION, plat)
        if managed:
            return managed

    for root in _playwright_cache_roots():
        if not root.is_dir():
            continue
        # Top-level .app only — `**` reaches into Helpers/*.app and returns
        # helper binaries (Alerts/Renderer/GPU), which exit immediately.
        candidates = (
            sorted(root.glob("chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
            + sorted(root.glob("chromium-*/chrome-linux*/chrome"))
            + sorted(root.glob("chromium_headless_shell-*/chrome-linux*/headless_shell"))
            + sorted(root.glob("chromium_headless_shell-*/chrome-mac*/headless_shell*"))
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


async def _download(url: str, dest: Path) -> str:
    """Stream-download url to dest; returns the sha256 of what arrived."""
    import httpx

    digest = hashlib.sha256()
    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(1 << 20):
                    digest.update(chunk)
                    f.write(chunk)
    return digest.hexdigest()


def _verify_signature(binary: Path, plat: str) -> str:
    """Best available signature check for the platform. Returns a note."""
    if plat.startswith("mac"):
        proc = subprocess.run(
            ["codesign", "-v", str(binary.parent.parent)], capture_output=True, text=True
        )
        return (
            "signature: valid"
            if proc.returncode == 0
            else f"signature: codesign failed — {proc.stderr.strip()[:120]}"
        )
    return "signature: not checked on this platform"


def _health_check(binary: Path) -> str:
    proc = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(f"health check failed: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


async def install_runtime() -> dict:
    """Download + verify + install the pinned runtime under app data."""
    plat = _platform_key()
    if plat is None:
        return {
            "status": "unsupported_platform",
            "detail": f"{sys.platform}/{platform.machine()} has no pinned runtime build",
        }

    import httpx

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
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
        binary = _binary_in_install(dest_dir, plat)
        if binary is None:
            return {"status": "error", "detail": "archive extracted but no binary found"}
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        sig_note = _verify_signature(binary, plat)
        version_out = await asyncio.to_thread(_health_check, binary)
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


def remove_runtime() -> dict:
    root = runtime_root() / RUNTIME_VERSION
    if not root.exists():
        return {"status": "not_installed"}
    shutil.rmtree(root)
    return {"status": "removed", "version": RUNTIME_VERSION}


def runtime_status() -> dict:
    binary = find_browser_binary()
    if binary is None:
        return {
            "status": "runtime_unavailable",
            "detail": (
                "No managed browser runtime found. Install the CaberOS "
                "browser runtime or set AGENTOS_BROWSER_BINARY."
            ),
            "version": RUNTIME_VERSION,
            "installable": _platform_key() is not None,
        }
    managed = runtime_root() / RUNTIME_VERSION
    return {
        "status": "ok",
        "binary": str(binary),
        "managed": binary.is_relative_to(managed),
        "version": RUNTIME_VERSION,
    }
