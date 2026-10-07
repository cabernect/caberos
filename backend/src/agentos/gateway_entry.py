"""Standalone FastAPI gateway entry point for desktop packaging."""

import os
import sys

import uvicorn

# Absolute, not relative: PyInstaller runs this file as __main__ with no parent
# package, so `from .logging_config import ...` raises ImportError in a packaged
# build ("attempted relative import with no known parent package"). Absolute
# imports work both packaged and via `python -m agentos.gateway_entry`.
from agentos.logging_config import configure_logging


def _verify_bundled_data() -> None:
    """Fail loudly when a packaged build is missing its bundled data files.

    PyInstaller's --add-data separator differs by platform (':' on POSIX, ';'
    on Windows). Using the wrong one does not error at build time: the data is
    simply omitted, and the app then starts with no default agents and no MCP
    catalog. That symptom points nowhere near its cause, so check it here where
    the message can name the actual problem.

    Only meaningful in a frozen build; from source these files are on disk.
    """
    if not getattr(sys, "frozen", False):
        return

    from agentos.seed import DEFAULTS_DIR

    missing = []
    if not DEFAULTS_DIR.is_dir() or not any(DEFAULTS_DIR.glob("*.yaml")):
        missing.append(str(DEFAULTS_DIR))

    catalog = DEFAULTS_DIR.parent / "mcp" / "catalog.yaml"
    if not catalog.is_file():
        missing.append(str(catalog))

    if missing:
        raise RuntimeError(
            "This build is missing bundled data files: "
            + ", ".join(missing)
            + ". The packaging step dropped them — check the PyInstaller "
            "--add-data separator (';' on Windows, ':' elsewhere)."
        )


def _start_parent_watchdog() -> None:
    """Exit the gateway when the parent Tauri app dies (B42 fencing).

    kill -9 / a crash gives the parent no chance to reap us, and SIGPIPE on
    the log pipe only fires if we happen to write — a silent orphan can hold
    the port and serve stale code indefinitely. ``getppid()`` changes when
    init (or a subreaper) adopts the orphan, and no legitimate reparenting
    happens while the app is alive, so any flip means the parent is gone.

    POSIX only — Windows skips this: the KILL_ON_JOB_CLOSE job object in
    ``gateway.rs`` already terminates the tree on force-kill.
    """
    if sys.platform == "win32":
        return

    import threading
    import time

    parent_pid = os.getppid()

    def _watch() -> None:
        while True:
            if os.getppid() != parent_pid:
                os._exit(0)
            time.sleep(2)

    threading.Thread(target=_watch, name="parent-watchdog", daemon=True).start()


def main() -> None:
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
    _verify_bundled_data()
    _start_parent_watchdog()
    log_level, access_log = configure_logging()
    uvicorn.run(
        "agentos.main:app",
        host=os.getenv("AGENTOS_CONTROL_PLANE_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENTOS_CONTROL_PLANE_PORT", "8081")),
        log_level=log_level,
        access_log=access_log,
        reload=os.getenv("AGENTOS_RELOAD", "false").strip().lower() in {"1", "true", "yes", "on"},
    )


if __name__ == "__main__":
    main()
