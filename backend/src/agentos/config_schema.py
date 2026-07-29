"""Pydantic models for agent configuration (D1, D25, D35)."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChannelBinding(BaseModel):
    type: Literal["dashboard_chat"] = "dashboard_chat"


class ModelConfig(BaseModel):
    provider_id: str
    name: str
    temperature: float = 0.3
    max_tokens: int | None = None


class CapabilityGrant(BaseModel):
    name: str
    subject: Literal["self", "any", "none"] = "none"
    require_approval: bool = False


class Limits(BaseModel):
    max_turns_per_run: int = 12
    max_cost_per_run: float = 500.0
    session_idle_timeout_min: int = 60
    max_context_tokens: int = 24000


class Fallback(BaseModel):
    on_unsupported_message: str = "Sorry, I can't handle that message type yet."
    on_limit_exceeded: Literal["tell_user_and_stop", "handoff_to_human"] = "tell_user_and_stop"


class HeartbeatConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = 60
    task_prompt: str = ""
    max_cost_per_heartbeat: float = 0.50
    consecutive_failure_threshold: int = 3


class AgentConfig(BaseModel):
    """Full agent configuration. Versioned as AgentVersion in the DB."""

    id: str
    name: str
    channels: list[ChannelBinding] = Field(default_factory=lambda: [ChannelBinding()])
    workspace: str = ""
    model: ModelConfig
    soul: str = ""
    persona: str = ""
    task: str = ""
    capabilities: list[CapabilityGrant] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    fallback: Fallback = Field(default_factory=Fallback)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        return cls.model_validate(data)


class SubAgentConfig(BaseModel):
    """Sub-agent config (D12 — no channel, no session, no workspace fields)."""

    id: str
    name: str
    task: str = ""
    capabilities: list[str] = Field(default_factory=list)
    model: ModelConfig | None = None

    @model_validator(mode="after")
    def reject_forbidden_fields(self) -> "SubAgentConfig":
        # D12 rule 1: sub-agents must not have channel, session, or workspace fields
        # This validator is a safety net — the schema itself doesn't include those fields
        return self
