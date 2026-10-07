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


def _port_holder(port: int) -> str | None:
    """Best-effort name of the process listening on port — for error text."""
    import shutil
    import subprocess

    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=5
            ).stdout
            pid = next(
                (
                    line.rsplit(None, 1)[-1]
                    for line in out.splitlines()
                    if f":{port} " in line and "LISTENING" in line
                ),
                None,
            )
            if not pid:
                return None
            task = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            name = task.split('","')[0].strip('"') if task else "unknown"
            return f"{name} (pid {pid})"
        if shutil.which("lsof"):
            out = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            lines = [line.split() for line in out.splitlines()[1:] if line.strip()]
            if lines:
                pid = lines[0][1]
                # lsof's COMMAND column truncates at 15 chars ("caberos-g") —
                # ps resolves the full path so the holder is unambiguous.
                name = subprocess.run(
                    ["ps", "-p", pid, "-o", "comm="],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip() or lines[0][0]
                return f"{name} (pid {pid})"
    except Exception:
        return None
    return None


def _claim_port_or_die(host: str, port: int) -> None:
    """Bind-probe the port before uvicorn — a foreign holder otherwise turns
    into a silent 'Connecting…' hang on the frontend (B42).

    Never kills the holder: a second app copy's live gateway is a legitimate
    process — report and let the operator decide.
    """
    import socket

    probe = socket.socket()
    try:
        probe.bind((host, port))
    except OSError as exc:
        holder = _port_holder(port)
        print(
            f"FATAL gateway cannot bind {host}:{port} — port is held by "
            f"{holder or f'another process ({exc})'}. "
            "Stop that process or run CaberOS on a different port.",
            file=sys.stderr,
        )
        sys.exit(3)  # distinct code — the Rust monitor reports it verbatim
    finally:
        probe.close()


def main() -> None:
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
    _verify_bundled_data()
    _start_parent_watchdog()
    host = os.getenv("AGENTOS_CONTROL_PLANE_HOST", "127.0.0.1")
    port = int(os.getenv("AGENTOS_CONTROL_PLANE_PORT", "8081"))
    _claim_port_or_die(host, port)
    log_level, access_log = configure_logging()
    uvicorn.run(
        "agentos.main:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=access_log,
        reload=os.getenv("AGENTOS_RELOAD", "false").strip().lower() in {"1", "true", "yes", "on"},
    )


if __name__ == "__main__":
    main()
