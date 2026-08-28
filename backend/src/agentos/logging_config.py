import logging
import os

LOG_LEVELS = {"critical", "error", "warning", "info", "debug"}


def get_log_level() -> str:
    value = os.getenv("AGENTOS_LOG_LEVEL", "info").strip().lower()
    return value if value in LOG_LEVELS else "info"


def get_log_access() -> bool:
    value = os.getenv("AGENTOS_LOG_ACCESS")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configure_logging() -> tuple[str, bool]:
    level = get_log_level()
    access = get_log_access()
    numeric_level = getattr(logging, level.upper())
    logging.basicConfig(level=numeric_level, format="%(levelname)s:%(name)s:%(message)s")
    logging.getLogger("agentos").setLevel(numeric_level)
    logging.getLogger("uvicorn.access").disabled = not access
    return level, access
