"""Application settings loaded from env vars and .env file."""

import os
from pathlib import Path

# Fix SSL cert verification for httpx on macOS (homebrew Python).
# httpx doesn't pick up homebrew's OpenSSL certs by default, which breaks
# litellm's live model registry fetch. Point SSL_CERT_FILE at the homebrew
# CA bundle if it exists and SSL_CERT_FILE isn't already set.
if "SSL_CERT_FILE" not in os.environ:
    for cert_path in [
        "/opt/homebrew/etc/ca-certificates/cert.pem",
        "/usr/local/etc/ca-certificates/cert.pem",
        "/etc/ssl/cert.pem",
    ]:
        if Path(cert_path).exists():
            os.environ["SSL_CERT_FILE"] = cert_path
            break

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Agent home dir (MEMORY.md, etc.)
    agent_home_root: Path = Path.home() / "agentos" / "agents"

    # System-level skills directory (shared across all agents)
    skills_dir: Path = Path("../skills")  # relative to backend cwd → repo root/skills

    # Server
    control_plane_host: str = "127.0.0.1"
    control_plane_port: int = 8081

    # Sandbox defaults
    sandbox_timeout: int = 30

    model_request_timeout: int = 120
    model_stream_idle_timeout: int = 30

    # HITL timeout — how long (seconds) to wait for human approval/elicitation
    # before auto-rejecting. 0 = wait forever (not recommended for production).
    hitl_timeout: int = 300  # 5 minutes

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
