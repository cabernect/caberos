"""Standalone FastAPI gateway entry point for desktop packaging."""

import os

# Must be set BEFORE litellm is imported anywhere — litellm fetches a
# model cost map from GitHub on import, which can take 30+ seconds
# through a corporate proxy. Use the local backup instead.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")

import uvicorn  # noqa: E402


def main() -> None:
    uvicorn.run(
        "agentos.main:app",
        host=os.getenv("AGENTOS_CONTROL_PLANE_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENTOS_CONTROL_PLANE_PORT", "8081")),
        log_level=os.getenv("AGENTOS_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
