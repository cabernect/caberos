"""Standalone FastAPI gateway entry point for desktop packaging."""

import os

import uvicorn

from .logging_config import configure_logging


def main() -> None:
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
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
