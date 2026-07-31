"""Application settings loaded from env vars and .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTOS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    db_path: Path = Path("data/agentos.db")

    # Secret store
    secret_key_path: Path = Path("data/secret.key")

    # Sandbox
    workspace_root: Path = Path("data/workspaces")

    # Agent home dir (MEMORY.md, etc.)
    agent_home_root: Path = Path.home() / "agentos" / "agents"

    # Server
    control_plane_host: str = "127.0.0.1"
    control_plane_port: int = 8081

    # Sandbox defaults
    sandbox_timeout: int = 30

    # HITL timeout — how long (seconds) to wait for human approval/elicitation
    # before auto-rejecting. 0 = wait forever (not recommended for production).
    hitl_timeout: int = 300  # 5 minutes

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def db_url_sync(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()
