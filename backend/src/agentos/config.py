"""Application settings loaded from env vars and .env file."""

import os
from pathlib import Path

from pydantic import Field

# Fix SSL cert verification for httpx/litellm on macOS.
# The Homebrew ca-certificates bundle includes corporate/proxy CAs (e.g. FPT
# captive portal) that the system /etc/ssl/cert.pem may not have. Always
# prefer the Homebrew bundle when available, even if SSL_CERT_FILE is already
# set to a different path.
for _cert_path in [
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/usr/local/etc/ca-certificates/cert.pem",
]:
    if Path(_cert_path).exists():
        os.environ["SSL_CERT_FILE"] = _cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = _cert_path
        break

from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTOS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database — SQLite by default (local-first, zero config).
    # To use Postgres or another backend, set AGENTOS_DATABASE_URL:
    #   postgresql+asyncpg://user:pass@localhost/agentos
    # When database_url is set, db_path is ignored.
    database_url: str = ""  # empty = use SQLite default below
    db_path: Path = Path("data/agentos.db")

    # Secret store
    secret_key_path: Path = Path("data/secret.key")

    # Sandbox
    workspace_root: Path = Path("data/workspaces")

    # Shared Knowledge Vault storage
    knowledge_root: Path = Path("data/knowledge")

    # Agent home dir (MEMORY.md, etc.)
    agent_home_root: Path = Path.home() / "agentos" / "agents"

    # Context bodies expire independently from conversation and usage records.
    context_capture_retention_days: int = Field(default=7, ge=1)
    context_capture_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    context_capture_max_payload_bytes: int = Field(default=1024 * 1024, ge=1)

    # System-level skills directory (shared across all agents)
    skills_dir: Path = Path("../skills")  # relative to backend cwd → repo root/skills
    # Operator-managed global/published skill storage (W6). Built-ins stay in
    # skills_dir; user-managed revisions are immutable dirs under this root.
    skills_store_root: Path = Path("data/skills-store")
    # Operator-owned import drafts (no host agent) — per-draft subdirs.
    skills_drafts_root: Path = Path("data/skills-drafts")

    # Server
    control_plane_host: str = "127.0.0.1"
    control_plane_port: int = 8081

    # Sandbox defaults
    sandbox_timeout: int = 30

    model_request_timeout: int = 120
    model_stream_idle_timeout: int = 60
    mcp_connection_timeout: float = 30.0

    db_lock_retries: int = 2
    db_lock_retry_delay: float = 0.1

    # HITL timeout — how long (seconds) to wait for human approval/elicitation
    # before auto-rejecting. 0 = wait forever (not recommended for production).
    hitl_timeout: int = 300  # 5 minutes

    # YOLO mode — skip all approval gates. Tools execute immediately without
    # waiting for operator confirmation. Useful for local dev/trusted environments.
    # Can be toggled at runtime via PUT /api/settings/yolo.
    yolo_mode: bool = False

    # models.dev catalog auto-refresh — daily upstream fetch of model
    # metadata/rates. Enabled by default; the bundled snapshot and last
    # successful refresh remain available offline. Explicit opt-outs win.
    # Set via PUT /api/settings/model-catalog or AGENTOS_MODEL_CATALOG_AUTO_REFRESH.
    model_catalog_auto_refresh: bool = True

    # Browser runtime override — path to a Chromium-family binary (Chrome,
    # Chromium, Edge, Brave). When set, the managed Chrome-for-Testing
    # install is skipped. The browser still launches with its own
    # --user-data-dir, so the operator's personal profile is never touched.
    # Set via AGENTOS_BROWSER_BINARY in .env or the env, or persisted via
    # PUT /api/settings/browser (env wins over the persisted value).
    browser_binary: str = ""
    # Explicit runtime binary overrides — env-only for now
    # (AGENTOS_RUNTIME_BINARY_OVERRIDES as a JSON dict of command→path).
    runtime_binary_overrides: dict[str, str] = {}

    @property
    def db_url(self) -> str:
        """Active database URL — custom backend if set, SQLite default otherwise."""
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def db_url_sync(self) -> str:
        """Sync URL for Alembic migrations (no async driver)."""
        if self.database_url:
            # Strip the async driver suffix for sync usage
            # e.g. postgresql+asyncpg://... → postgresql://...
            if "+" in self.database_url.split("://")[0]:
                scheme = self.database_url.split("+")[0]
                rest = self.database_url.split("://", 1)[1]
                return f"{scheme}://{rest}"
            return self.database_url
        return f"sqlite:///{self.db_path}"


settings = Settings()


def env_pinned(key: str) -> bool:
    """True when AGENTOS_<KEY> is set in the process env or the .env file.

    Real env vars land in os.environ; .env-file values are loaded by
    pydantic without touching os.environ, so both must be checked to know
    whether the operator explicitly pinned a setting outside the UI."""
    import re

    env_key = f"AGENTOS_{key.upper()}"
    if os.environ.get(env_key):
        return True
    env_file = Path(".env")
    if env_file.is_file():
        try:
            pattern = rf"^\s*(?:export\s+)?{re.escape(env_key)}\s*="
            if re.search(pattern, env_file.read_text(), re.MULTILINE):
                return True
        except Exception:
            pass
    return False


def _apply_persisted_overrides() -> None:
    """Overlay operator-editable settings saved under the data dir
    (Settings → Browser writes browser_binary here). Survives restarts
    and rides the Docker /data volume; env vars still win for ops."""
    import json

    path = settings.db_path.parent / "app-settings.json"
    if not path.is_file():
        return
    try:
        saved = json.loads(path.read_text())
    except Exception:
        return
    if not isinstance(saved, dict):
        return
    capture_keys = {
        "context_capture_retention_days",
        "context_capture_max_bytes",
        "context_capture_max_payload_bytes",
    }
    for key in (
        "browser_binary",
        "yolo_mode",
        "model_catalog_auto_refresh",
        *capture_keys,
    ):
        if key not in saved or env_pinned(key):
            continue
        value = saved[key]
        if key in capture_keys and not (
            isinstance(value, int) and not isinstance(value, bool) and value > 0
        ):
            # Malformed persisted policy is ignored, not applied — the
            # settings default (or env pin) stands.
            continue
        setattr(settings, key, value)


_apply_persisted_overrides()


def persist_settings(values: dict[str, object]) -> None:
    """Write multiple operator-editable settings atomically — one merged
    overlay write, then live singletons. Unknown keys are preserved."""
    import json
    import os
    import tempfile

    path = settings.db_path.parent / "app-settings.json"
    saved: dict = {}
    if path.is_file():
        raw = path.read_text()
        if raw.strip():
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"app-settings.json is malformed — refusing to overwrite: {e}"
                ) from e
            if not isinstance(loaded, dict):
                raise ValueError(
                    "app-settings.json must contain a JSON object — refusing to overwrite"
                )
            saved = loaded
    for key, value in values.items():
        if value in (None, ""):
            saved.pop(key, None)
        else:
            saved[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(saved, indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # Mutate singleton only after the durable write landed.
    for key, value in values.items():
        setattr(settings, key, value if value is not None else "")


def persist_setting(key: str, value: object) -> None:
    """Write one operator-editable setting to the data-dir overlay."""
    persist_settings({key: value})
