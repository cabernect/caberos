"""Standalone FastAPI gateway entry point for desktop packaging."""

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
    uvicorn.run(
        "agentos.main:app",
        host=os.getenv("AGENTOS_CONTROL_PLANE_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENTOS_CONTROL_PLANE_PORT", "8081")),
        log_level=os.getenv("AGENTOS_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
