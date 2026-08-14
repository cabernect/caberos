"""LiteLLM adapter — real model access via LiteLLM (D6, D39).

Loads ProviderConfig from the DB at call time, decrypts the API key via
the Fernet secret store, and calls LiteLLM's completion() endpoint.
Supports OpenAI, Anthropic, Google, Ollama, and any provider LiteLLM supports.

Implements the same interface as ScriptedModel so the Harness can use either.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..config_schema import ModelConfig
from ..models.provider import Provider
from ..providers.litellm_transport import LiteLLMTransport
from ..secret_store import decrypt
from .scripted_model import ScriptedResponse

# Auto-inject summary="detailed" when reasoning_effort is set but no explicit
# summary is provided. This ensures reasoning content is returned in streams
# even if a caller sets reasoning_effort as a plain string.
# See: https://docs.litellm.ai/docs/reasoning_content#openai-responses-api---auto-summary-control
litellm.reasoning_auto_summary = True

log = __import__("logging").getLogger("agentos.harness.litellm")


@dataclass
class LiteLLMAdapter:
    """Real model adapter backed by LiteLLM.

    Usage:
        adapter = LiteLLMAdapter(db_session)
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=history,
            tools=tool_schemas,
        )
    """

    db: AsyncSession
    transport: LiteLLMTransport = field(default_factory=LiteLLMTransport, repr=False)
    _provider_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    # --- Tool name sanitization ---
    # Some providers (OpenAI-compatible) reject tool names with dots, requiring
    # ^[a-zA-Z0-9_-]+$. We sanitize mcp.playwright.browser_navigate →
    # mcp_playwright_browser_navigate at the API boundary, and restore the
    # original name when the model calls the tool.

    @staticmethod
    def _sanitize_tool_name(name: str) -> str:
        return name.replace(".", "_")

    @staticmethod
    def _sanitize_tools(tools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Sanitize tool names for the API. Returns (sanitized_tools, restore_map).

        restore_map maps sanitized_name → original_name.
        """
        restore_map: dict[str, str] = {}
        sanitized: list[dict[str, Any]] = []
        for tool in tools:
            fn = tool.get("function", {})
            orig = fn.get("name", "")
            if "." not in orig:
                sanitized.append(tool)
                continue
            safe = LiteLLMAdapter._sanitize_tool_name(orig)
            restore_map[safe] = orig
            new_tool = {**tool, "function": {**fn, "name": safe}}
            sanitized.append(new_tool)
        return sanitized, restore_map

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize tool names in message history (assistant tool_calls)."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                new_msg = {**msg}
                new_msg["tool_calls"] = [
                    {
                        **tc,
                        "function": {
                            **tc.get("function", {}),
                            "name": LiteLLMAdapter._sanitize_tool_name(
                                tc.get("function", {}).get("name", "")
                            ),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
                result.append(new_msg)
            else:
                result.append(msg)
        return result

    @staticmethod
    def _restore_tool_names(
        tool_calls: list[dict[str, Any]], restore_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Restore original tool names in model response tool calls."""
        if not restore_map:
            return tool_calls
        return [{**tc, "name": restore_map.get(tc["name"], tc["name"])} for tc in tool_calls]

    async def _load_provider(self, provider_id: str) -> dict[str, Any]:
        """Load and decrypt provider config (D39). Cached per session."""
        if provider_id in self._provider_cache:
            return self._provider_cache[provider_id]

        result = await self.db.execute(select(Provider).where(Provider.id == provider_id))
        provider = result.scalar_one_or_none()
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        api_key = ""
        if provider.encrypted_key:
            api_key = decrypt(provider.encrypted_key)

        config: dict[str, Any] = {
            "api_key": api_key,
            "base_url": provider.base_url,
            "org_id": provider.org_id,
            "extra_params": json.loads(provider.extra_params) if provider.extra_params else {},
            "type": provider.type,
        }
        self._provider_cache[provider_id] = config
        return config

    async def get_model_info(self, agent_model: ModelConfig) -> dict[str, Any]:
        """Return model string and provider credentials for auxiliary LLM calls
        (e.g. compaction summaries, title generation).
        """
        provider = await self._load_provider(agent_model.provider_id)
        model_str, api_base = self._route_model(provider, agent_model.name)
        return {
            "model_str": model_str,
            "api_key": provider["api_key"] or None,
            "base_url": api_base or provider["base_url"] or None,
        }

    @staticmethod
    def _model_family(provider: dict[str, Any], model_name: str) -> str:
        """Return the provider's generic LiteLLM protocol family."""
        return provider["type"]

    @staticmethod
    def _route_model(provider: dict[str, Any], model_name: str) -> tuple[str, str | None]:
        return f"{provider['type']}/{model_name}", provider["base_url"]

    @staticmethod
    def _cached_tokens(usage: Any) -> int | None:
        """Extract provider-reported cached input tokens when available."""
        if usage is None:
            return None

        def get_value(value: Any, name: str) -> Any:
            if isinstance(value, dict):
                return value.get(name)
            return getattr(value, name, None)

        details = get_value(usage, "prompt_tokens_details")
        for source in (details, usage):
            for name in ("cached_tokens", "cache_read_input_tokens"):
                value = get_value(source, name)
                if value is not None:
                    return int(value)
        return None

    @staticmethod
    def _apply_thinking_kwargs(
        kwargs: dict[str, Any],
        agent_model: ModelConfig,
        provider: dict[str, Any],
        family: str | None = None,
    ) -> None:
        enabled = agent_model.thinking_enabled
        if enabled or enabled is False or (enabled is None and kwargs.get("tools")):
            kwargs["reasoning_effort"] = (
                agent_model.thinking_effort or "medium" if enabled else "none"
            )

    async def complete(
        self,
        agent_model: ModelConfig | None = None,
        messages: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> ScriptedResponse:
        """Call the model via LiteLLM and return a normalized response."""
        if agent_model is None:
            raise ValueError("agent_model is required for LiteLLMAdapter")
        if messages is None:
            messages = []

        provider = await self._load_provider(agent_model.provider_id)
        if self._model_family(provider, agent_model.name) == "responses":
            return await self._complete_responses(provider, agent_model, messages, tools)

        # Build the LiteLLM model string — may override the prefix for
        # multi-backend proxies like OpenCode Zen (e.g. anthropic/claude-*).
        model_str, api_base = self._route_model(provider, agent_model.name)

        kwargs: dict[str, Any] = {
            "model": model_str,
            "messages": messages,
        }

        # Provider-specific params
        if provider["api_key"]:
            kwargs["api_key"] = provider["api_key"]
        if api_base or provider["base_url"]:
            kwargs["api_base"] = api_base or provider["base_url"]
        if provider["org_id"]:
            kwargs["organization"] = provider["org_id"]
        kwargs.update(provider["extra_params"])

        if agent_model.max_tokens:
            kwargs["max_tokens"] = agent_model.max_tokens

        # Tools are already in OpenAI format: {"type": "function", "function": {...}}
        # Sanitize tool names for providers that reject dots (e.g. OpenAI-compatible)
        restore_map: dict[str, str] = {}
        if tools:
            tools, restore_map = self._sanitize_tools(tools)
            kwargs["tools"] = tools
        # Sanitize tool names in message history too
        messages = self._sanitize_messages(messages)
        kwargs["messages"] = messages

        # Thinking/reasoning controls use the endpoint-specific field.
        family = self._model_family(provider, agent_model.name)
        self._apply_thinking_kwargs(kwargs, agent_model, provider, family)

        # Call LiteLLM
        response = await self.transport.completion(**kwargs)

        # Extract the choice
        choice = response.choices[0]
        message = choice.message

        # Parse tool calls if present
        tool_calls: list[dict[str, Any]] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = {}
                if tc.function.arguments:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                tool_calls.append(
                    {
                        "id": tc.id or str(uuid.uuid4()),
                        "name": tc.function.name,
                        "args": args,
                    }
                )
        # Restore original tool names (mcp_playwright_* → mcp.playwright.*)
        tool_calls = self._restore_tool_names(tool_calls, restore_map)

        # Extract token usage and cost
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        cached_tokens = self._cached_tokens(usage)

        # LiteLLM provides cost via response.cost, but it's not always set
        cost = 0.0
        try:
            if hasattr(response, "cost") and response.cost:
                cost = float(response.cost)
        except (TypeError, ValueError):
            cost = 0.0
        if cost == 0.0 and tokens_in > 0:
            try:
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=model_str,
                    prompt_tokens=tokens_in,
                    completion_tokens=tokens_out,
                )
                cost = prompt_cost + completion_cost
            except Exception:
                pass

        content = message.content or ""

        return ScriptedResponse(
            tool_calls=tool_calls,
            content=content,
            thinking="",  # reasoning tokens handled separately if needed
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            cost=cost,
        )

    async def complete_stream(
        self,
        agent_model: ModelConfig | None = None,
        messages: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ):
        """Call the model with streaming. Yields (delta_type, content) tuples.

        delta_type is one of:
            "token" — a chunk of output text
            "thinking" — a chunk of reasoning text
            "tool_call" — a complete tool call (accumulated from deltas)
            "done" — final signal with usage/cost info

        The final "done" event carries the full ScriptedResponse.
        """
        if agent_model is None:
            raise ValueError("agent_model is required for LiteLLMAdapter")
        if messages is None:
            messages = []

        provider = await self._load_provider(agent_model.provider_id)
        if self._model_family(provider, agent_model.name) == "responses":
            async for event in self._complete_responses_stream(
                provider, agent_model, messages, tools
            ):
                yield event
            return

        model_str, api_base = self._route_model(provider, agent_model.name)

        # Sanitize tool names for providers that reject dots
        restore_map: dict[str, str] = {}
        if tools:
            tools, restore_map = self._sanitize_tools(tools)
        messages = self._sanitize_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model_str,
            "messages": messages,
            "stream": True,
        }

        if provider["api_key"]:
            kwargs["api_key"] = provider["api_key"]
        if api_base or provider["base_url"]:
            kwargs["api_base"] = api_base or provider["base_url"]
        if provider["org_id"]:
            kwargs["organization"] = provider["org_id"]
        kwargs.update(provider["extra_params"])

        if agent_model.max_tokens:
            kwargs["max_tokens"] = agent_model.max_tokens

        if tools:
            # Tools are already in OpenAI format
            kwargs["tools"] = tools

        # Thinking/reasoning controls use the endpoint-specific field.
        family = self._model_family(provider, agent_model.name)
        self._apply_thinking_kwargs(kwargs, agent_model, provider, family)

        # Request usage info in streaming responses (OpenAI-compatible)
        kwargs["stream_options"] = {"include_usage": True}

        # Call LiteLLM with streaming
        stream = await asyncio.wait_for(
            self.transport.completion(**kwargs), timeout=settings.model_request_timeout
        )

        full_content = ""
        full_thinking = ""
        tool_calls_map: dict[int, dict[str, Any]] = {}
        tokens_in = 0
        tokens_out = 0
        cached_tokens: int | None = None
        cost = 0.0

        stream_iterator = aiter(stream)
        while True:
            try:
                chunk = await asyncio.wait_for(
                    anext(stream_iterator), timeout=settings.model_stream_idle_timeout
                )
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Model stream was idle for {settings.model_stream_idle_timeout}s"
                ) from exc

            if not chunk.choices:
                # Usage info sometimes comes in a separate chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    tokens_in = chunk.usage.prompt_tokens or 0
                    tokens_out = chunk.usage.completion_tokens or 0
                    cached_tokens = self._cached_tokens(chunk.usage)
                continue

            delta = chunk.choices[0].delta

            # Reasoning/thinking tokens (some models)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                full_thinking += delta.reasoning_content
                yield ("thinking", delta.reasoning_content)

            # Some providers (e.g. OpenAI Responses API bridge) may put
            # reasoning text in delta.reasoning instead of delta.reasoning_content
            if hasattr(delta, "reasoning") and delta.reasoning:
                reasoning_text = (
                    delta.reasoning if isinstance(delta.reasoning, str) else str(delta.reasoning)
                )
                full_thinking += reasoning_text
                yield ("thinking", reasoning_text)

            # Content tokens
            if delta.content:
                full_content += delta.content
                yield ("token", delta.content)

            # Tool call deltas (accumulated)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index or 0
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc_delta.id or str(uuid.uuid4()),
                            "name": "",
                            "args": "",
                        }
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_map[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_map[idx]["args"] += tc_delta.function.arguments

        # Parse accumulated tool calls
        tool_calls: list[dict[str, Any]] = []
        for idx in sorted(tool_calls_map):
            tc = tool_calls_map[idx]
            args = {}
            if tc["args"]:
                try:
                    args = json.loads(tc["args"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
            tool_calls.append({"id": tc["id"], "name": tc["name"], "args": args})
        # Restore original tool names (mcp_playwright_* → mcp.playwright.*)
        tool_calls = self._restore_tool_names(tool_calls, restore_map)

        # If we didn't get usage from streaming, estimate
        if tokens_in == 0:
            tokens_in = sum(len(m.get("content", "")) for m in messages) // 4
        if tokens_out == 0:
            tokens_out = (len(full_content) + len(full_thinking)) // 4

        # Get cost — LiteLLM doesn't always set stream.cost for streaming
        # responses, so fall back to calculating it from token counts
        cost = 0.0
        try:
            if hasattr(stream, "cost") and stream.cost:
                cost = float(stream.cost)
        except (TypeError, ValueError):
            cost = 0.0
        if cost == 0.0 and tokens_in > 0:
            try:
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=model_str,
                    prompt_tokens=tokens_in,
                    completion_tokens=tokens_out,
                )
                cost = prompt_cost + completion_cost
            except Exception:
                pass

        final = ScriptedResponse(
            tool_calls=tool_calls,
            content=full_content,
            thinking=full_thinking,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            cost=cost,
        )
        yield ("done", final)

    async def validate_model(self, provider_id: str, model_name: str) -> bool:
        """Validate a model through the provider catalog."""
        from ..providers.model_catalog import LiteLLMModelCatalog

        return await LiteLLMModelCatalog(self).validate_model(provider_id, model_name)

    async def discover_models(self, provider_id: str) -> list[dict[str, Any]]:
        """Discover models through the provider catalog."""
        from ..providers.model_catalog import LiteLLMModelCatalog

        return await LiteLLMModelCatalog(self).discover_models(provider_id)
