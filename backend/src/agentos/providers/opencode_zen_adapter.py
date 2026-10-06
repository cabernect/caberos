"""OpenCode Zen protocol routing on top of LiteLLM."""

from typing import Any

from ..config_schema import ModelConfig


class OpenCodeZenMixin:
    """OpenCode Zen routing, reasoning fields, and endpoint selection.

    This mixin is combined with the generic LiteLLM adapter so the transport
    remains LiteLLM while Zen-specific protocol behavior stays local. The
    Responses-API call/parse helpers live on LiteLLMAdapter — they're the
    generic OpenAI protocol, shared with plain api.openai.com providers.
    """

    @staticmethod
    def _is_opencode_zen(provider: dict[str, Any]) -> bool:
        return (
            provider.get("type") == "openai"
            and "opencode.ai/zen" in (provider.get("base_url") or "").lower()
        )

    @staticmethod
    def _model_family(provider: dict[str, Any], model_name: str) -> str:
        name = model_name.lower()
        if name.startswith(("gpt-", "grok-")):
            return "responses"
        if name.startswith(("claude-", "qwen")):
            return "anthropic_messages"
        if name.startswith("gemini-"):
            return "gemini"
        return "chat_completions"

    @staticmethod
    def _route_model(provider: dict[str, Any], model_name: str) -> tuple[str, str | None]:
        family = OpenCodeZenMixin._model_family(provider, model_name)
        prefix = {
            "responses": "openai",
            "anthropic_messages": "anthropic",
            "gemini": "gemini",
            "chat_completions": "openai",
        }[family]
        return f"{prefix}/{model_name}", provider["base_url"]

    @staticmethod
    def _effort_budget(effort: str | None) -> int:
        return {
            "minimal": 1024,
            "low": 4096,
            "medium": 8192,
            "high": 16384,
            "xhigh": 32768,
            "max": 32768,
        }.get(effort or "medium", 8192)

    @staticmethod
    def _apply_thinking_kwargs(
        kwargs: dict[str, Any],
        agent_model: ModelConfig,
        provider: dict[str, Any],
        family: str | None = None,
    ) -> None:
        family = family or OpenCodeZenMixin._model_family(provider, agent_model.name)
        has_tools = bool(kwargs.get("tools"))
        enabled = agent_model.thinking_enabled

        if family == "anthropic_messages":
            if enabled:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": OpenCodeZenMixin._effort_budget(agent_model.thinking_effort),
                }
            return

        if family == "gemini":
            if enabled is not None:
                kwargs.setdefault("extra_body", {})["generationConfig"] = {
                    "thinkingConfig": {
                        "thinkingBudget": (
                            OpenCodeZenMixin._effort_budget(agent_model.thinking_effort)
                            if enabled
                            else 0
                        )
                    }
                }
            return

        if family == "chat_completions":
            if enabled:
                kwargs.setdefault("extra_body", {})["reasoning_effort"] = (
                    agent_model.thinking_effort or "medium"
                )
            elif enabled is False or (enabled is None and has_tools):
                kwargs.setdefault("extra_body", {})["reasoning_effort"] = "none"
            return
