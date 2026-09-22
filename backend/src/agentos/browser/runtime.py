"""Managed browser runtime discovery.

For now the runtime is *found*, not installed: the full first-use installer
(download → hash-verify → install under app data → health check) is a later
W4 slice. Resolution order:

1. ``AGENTOS_BROWSER_BINARY`` env override — explicit operator choice.
2. Playwright-managed cache (``~/Library/Caches/ms-playwright`` / XDG cache)
   — a Chromium-family binary already on the machine.
3. ``runtime_unavailable`` — callers report honestly, never silently install.
"""

from __future__ import annotations

import os
from pathlib import Path


def _playwright_cache_roots() -> list[Path]:
    roots = []
    if custom := os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        roots.append(Path(custom))
    roots.append(Path.home() / "Library" / "Caches" / "ms-playwright")  # macOS
    roots.append(Path.home() / ".cache" / "ms-playwright")  # Linux
    return roots


def find_browser_binary() -> Path | None:
    """Locate a compatible Chromium-family binary, or None."""
    if override := os.environ.get("AGENTOS_BROWSER_BINARY"):
        p = Path(override).expanduser()
        return p if p.is_file() else None

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


def runtime_status() -> dict:
    binary = find_browser_binary()
    if binary is None:
        return {
            "status": "runtime_unavailable",
            "detail": (
                "No managed browser runtime found. Install the CaberOS "
                "browser runtime (Settings → Dependencies) or set "
                "AGENTOS_BROWSER_BINARY."
            ),
        }
    return {"status": "ok", "binary": str(binary)}
