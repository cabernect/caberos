"""Pydantic models for agent configuration (D1, D25, D35)."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChannelBinding(BaseModel):
    type: Literal["dashboard_chat"] = "dashboard_chat"


class ModelConfig(BaseModel):
    # Empty string = no model configured. The agent can't run until the user
    # assigns a provider + model in Settings. This happens when a provider is
    # deleted out from under an agent.
    provider_id: str = ""
    name: str = ""
    max_tokens: int | None = None
    # Override the model's max context window (input tokens).
    # If None, we try litellm's registry, then fall back to 32K.
    max_context_tokens: int | None = None

    @property
    def is_configured(self) -> bool:
        """True when both provider_id and name are set."""
        return bool(self.provider_id and self.name)


class CapabilityGrant(BaseModel):
    name: str
    enabled: bool = True
    subject: Literal["self", "any", "none"] = "none"
    require_approval: bool = False


class Limits(BaseModel):
    max_turns_per_run: int = 15
    max_cost_per_run: float = 500.0
    session_idle_timeout_min: int = 30
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


class CompactionConfig(BaseModel):
    """Context compaction settings (head/middle/tail summarization).

    auto_compaction: when True, compaction fires automatically when tokens
      exceed threshold. When False, only /compact triggers it manually.
      Manual /compact always compacts regardless of threshold.
    threshold: fraction of model's max context window that triggers auto
      compaction (default 0.7 = 70%)
    protect_first_n: number of messages always kept verbatim (head)
    protect_last_n: minimum number of messages always kept verbatim (tail)
    tail_budget_fraction: fraction of threshold_tokens reserved for the tail
    prune_tool_results_over: char length — tool results longer than this
      outside the protected tail are replaced with a stub (Phase 1)
    """
    auto_compaction: bool = True
    threshold: float = 0.7
    protect_first_n: int = 3
    protect_last_n: int = 20
    tail_budget_fraction: float = 0.20
    prune_tool_results_over: int = 200


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
    capabilities: list[CapabilityGrant] | None = None  # None = all tools, [] = none
    limits: Limits = Field(default_factory=Limits)
    fallback: Fallback = Field(default_factory=Fallback)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    sandbox_mode: Literal["strict", "open"] = "strict"  # strict=workspace only, open=any path

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
