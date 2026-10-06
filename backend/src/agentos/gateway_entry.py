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


def main() -> None:
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
    _verify_bundled_data()
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
