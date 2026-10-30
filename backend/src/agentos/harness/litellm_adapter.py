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
from urllib.parse import urlparse

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..config_schema import ModelConfig
from ..models.provider import Provider
from ..providers.litellm_transport import LiteLLMTransport
from ..secret_store import decrypt
from ..services.call_accounting import (
    CallRateSnapshot,
    capture_call_rates,
    unknown_call_rates,
)
from ..services.context_capture import capture_dispatch
from .scripted_model import ScriptedResponse

# Auto-inject summary="detailed" when reasoning_effort is set but no explicit
# summary is provided. This ensures reasoning content is returned in streams
# even if a caller sets reasoning_effort as a plain string.
# See: https://docs.litellm.ai/docs/reasoning_content#openai-responses-api---auto-summary-control
litellm.reasoning_auto_summary = True

# Drop unsupported params instead of erroring (e.g. reasoning_effort on
# models/providers that don't support it).
litellm.drop_params = True

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

    async def _capture_rates(self, agent_model: ModelConfig, provider: dict) -> CallRateSnapshot:
        """Frozen pre-call rate authority — a capture failure degrades to
        the unknown snapshot so a genuine provider amount is preserved."""
        try:
            return await capture_call_rates(
                self.db, agent_model.provider_id, agent_model.name, provider
            )
        except Exception:
            log.debug("rate capture failed; call proceeds unknown", exc_info=True)
            return unknown_call_rates(agent_model.provider_id, agent_model.name, provider)

    @staticmethod
    def _apply_assessment(
        snapshot: CallRateSnapshot | None, raw: Any, family: str
    ) -> tuple[int, int, int | None, int | None, float, str | None, dict | None]:
        """Canonical legacy fields from assessment.usage — the normalizer's
        native tokens only, never SDK extractors or text-length guesses."""
        if snapshot is None:
            return 0, 0, None, None, 0.0, "unknown", None
        assessment = snapshot.assess(raw, family=family)
        usage = assessment.usage
        return (
            int(usage.input_tokens or 0) if usage else 0,
            int(usage.output_tokens or 0) if usage else 0,
            usage.cache_read_tokens if usage else None,
            usage.reasoning_tokens if usage else None,
            float(assessment.amount) if assessment.amount is not None else 0.0,
            assessment.source,
            snapshot.receipt(assessment),
        )

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

        extra_params = json.loads(provider.extra_params) if provider.extra_params else {}
        if provider.encrypted_credentials:
            # Named credentials (azure api_version, bedrock aws_*) merge
            # under explicit extra_params so every call site that applies
            # extras — chat, responses, streams, probes, aux calls — gets
            # them without each site knowing this column exists.
            creds = json.loads(decrypt(provider.encrypted_credentials))
            extra_params = {**creds, **extra_params}

        config: dict[str, Any] = {
            "api_key": api_key,
            "base_url": provider.base_url,
            "org_id": provider.org_id,
            "extra_params": extra_params,
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
        snapshot = await self._capture_rates(agent_model, provider)

        return {
            "model_str": model_str,
            "api_key": provider["api_key"] or None,
            "base_url": api_base or provider["base_url"] or None,
            # Extras already carry decrypted credentials — aux callers
            # (compaction summaries) merge them so azure/bedrock work
            # off the main dispatch path too.
            "extra_params": provider["extra_params"],
            # Aux calls (compaction summaries) must use the same endpoint —
            # reasoning models reject even plain calls on chat completions
            # when params like max_tokens are sent.
            "use_responses": self._model_family(provider, agent_model.name) == "responses",
            # Frozen rate snapshot + resolved metadata — aux callers
            # (summaries, compaction budgets) pin the same authority.
            "accounting": snapshot,
            "resolved_model": (json.loads(snapshot.model_metadata_json) if snapshot else {}),
        }

    @staticmethod
    def _model_family(provider: dict[str, Any], model_name: str) -> str:
        """Return the provider's generic LiteLLM protocol family.

        Plain api.openai.com providers default to the Responses API — it's
        OpenAI's current API, every catalog model works on it (including
        non-reasoning ones), and reasoning models only accept tools there.
        OpenAI-compatible custom base_urls (vLLM, LM Studio, proxies) stay
        on chat completions — most don't implement /v1/responses — with a
        retry to Responses when the server asks for it.
        """
        if provider["type"] == "openai":
            base = (provider.get("base_url") or "").lower()
            if not base:
                return "responses"
            host = urlparse(base if "://" in base else f"https://{base}").hostname or ""
            if host == "api.openai.com":
                return "responses"
        return provider["type"]

    @staticmethod
    def _route_model(provider: dict[str, Any], model_name: str) -> tuple[str, str | None]:
        return f"{provider['type']}/{model_name}", provider["base_url"]

    @staticmethod
    def _reassert_runtime(
        kwargs: dict[str, Any],
        *,
        model: str,
        messages: list | None = None,
        input_items: list | None = None,
        tools: list | None,
        stream: bool | None,
    ) -> None:
        """Re-assert runtime-owned request fields AFTER provider
        extra_params merged. Extras may enrich (headers, sampling
        controls) but can never reroute the billed model, replace the
        counted messages/tools, or change the request stream shape."""
        kwargs["model"] = model
        if messages is not None:
            kwargs["messages"] = messages
            # The opposite endpoint's payload key can never ride along —
            # an extras-supplied input would bypass counted context.
            kwargs.pop("input", None)
        if input_items is not None:
            kwargs["input"] = input_items
            kwargs.pop("messages", None)
        if tools:
            kwargs["tools"] = tools
        else:
            kwargs.pop("tools", None)
        if stream is None:
            kwargs.pop("stream", None)
        else:
            kwargs["stream"] = stream

    @staticmethod
    def _missing_on_responses(exc: Exception) -> bool:
        """True when the model doesn't exist on /v1/responses — chat-only
        models (e.g. gpt-3.5-turbo) 404 there, so fall back to chat
        completions. A genuinely bogus model name also lands here, but the
        chat attempt then fails honestly with its own not-found error."""
        msg = str(exc).lower()
        return "model_not_found" in msg or "does not exist or you do not have access" in msg

    @staticmethod
    def _needs_responses_api(exc: Exception) -> bool:
        """True when the server tells us to retry on the Responses API —
        e.g. 'use /v1/responses' for reasoning models given tools on
        chat completions. Narrow match: honest failure otherwise."""
        msg = str(exc).lower()
        return "/v1/responses" in msg or "responses api" in msg

    # --- Responses API (OpenAI /v1/responses protocol) ---
    # Generic helpers — shared by plain OpenAI providers and OpenCode Zen.

    @staticmethod
    def _responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "name": tool.get("function", {}).get("name", ""),
                "description": tool.get("function", {}).get("description", ""),
                "parameters": tool.get("function", {}).get("parameters", {}),
            }
            for tool in tools
        ]

    @staticmethod
    def _responses_tool_output(content: Any) -> Any:
        """Translate OpenAI-style tool content for the Responses API."""
        if not isinstance(content, list):
            return content
        converted = []
        for part in content:
            if part.get("type") == "text":
                converted.append({"type": "input_text", "text": part.get("text", "")})
            elif part.get("type") == "image_url":
                converted.append(
                    {
                        "type": "input_image",
                        "image_url": part.get("image_url", {}).get("url", ""),
                    }
                )
        return converted

    @staticmethod
    def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "assistant" and message.get("tool_calls"):
                if message.get("content"):
                    result.append({"role": "assistant", "content": message["content"]})
                for call in message["tool_calls"]:
                    function = call.get("function", {})
                    result.append(
                        {
                            "type": "function_call",
                            "call_id": call.get("id") or str(uuid.uuid4()),
                            "name": function.get("name", ""),
                            "arguments": function.get("arguments", "{}"),
                        }
                    )
            elif role == "tool":
                result.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id", ""),
                        "output": LiteLLMAdapter._responses_tool_output(message.get("content", "")),
                    }
                )
            else:
                result.append(message)
        return result

    @staticmethod
    def _response_attr(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _parse_response_output(cls, response: Any) -> tuple[str, str, list[dict[str, Any]]]:
        content = ""
        thinking = ""
        tool_calls: list[dict[str, Any]] = []
        for item in cls._response_attr(response, "output", []) or []:
            item_type = cls._response_attr(item, "type", "")
            if item_type == "function_call":
                arguments = cls._response_attr(item, "arguments", "") or "{}"
                try:
                    args = json.loads(arguments)
                except (TypeError, json.JSONDecodeError):
                    args = {}
                tool_calls.append(
                    {
                        "id": cls._response_attr(item, "call_id") or str(uuid.uuid4()),
                        "name": cls._response_attr(item, "name", ""),
                        "args": args,
                    }
                )
                continue
            if item_type == "reasoning":
                for summary in cls._response_attr(item, "summary", []) or []:
                    text = cls._response_attr(summary, "text", "")
                    if text:
                        thinking += text
                continue
            if item_type == "message":
                for block in cls._response_attr(item, "content", []) or []:
                    if cls._response_attr(block, "type", "") in ("output_text", "text"):
                        content += cls._response_attr(block, "text", "") or ""
        return content, thinking, tool_calls

    @staticmethod
    def _reasoning_tokens(usage: Any) -> int | None:
        """Provider-reported reasoning/thinking output tokens.

        `completion_tokens_details.reasoning_tokens` (chat) or
        `output_tokens_details.reasoning_tokens` (responses) or a top-level
        `reasoning_tokens`, across dicts and attr-objects alike. These are
        already counted inside tokens_out. None stays None; an explicit 0
        stays 0.
        """
        if usage is None:
            return None

        def get(value: Any, name: str) -> Any:
            if value is None:
                return None
            if isinstance(value, dict):
                return value.get(name)
            return getattr(value, name, None)

        for detail_name in ("completion_tokens_details", "output_tokens_details"):
            reported = get(get(usage, detail_name), "reasoning_tokens")
            if reported is not None:
                return int(reported)
        reported = get(usage, "reasoning_tokens")
        return int(reported) if reported is not None else None

    @classmethod
    def _response_usage(cls, response: Any) -> tuple[int, int, int | None, int | None]:
        usage = cls._response_attr(response, "usage")
        details = cls._response_attr(usage, "input_tokens_details")
        cached = cls._response_attr(details, "cached_tokens")
        if cached is None:
            cached = cls._response_attr(usage, "cached_tokens")
        return (
            int(cls._response_attr(usage, "input_tokens", 0) or 0),
            int(cls._response_attr(usage, "output_tokens", 0) or 0),
            int(cached) if cached is not None else None,
            cls._reasoning_tokens(usage),
        )

    async def _complete_responses(
        self,
        provider: dict[str, Any],
        agent_model: ModelConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> ScriptedResponse:
        model_str, api_base = self._route_model(provider, agent_model.name)
        sanitized_messages = self._sanitize_messages(messages)
        sanitized_tools, restore_map = self._sanitize_tools(tools or [])
        input_items = self._responses_input(sanitized_messages)
        responses_tools = self._responses_tools(sanitized_tools)
        kwargs: dict[str, Any] = {
            "model": model_str,
            "input": input_items,
            "api_key": provider["api_key"] or None,
            "api_base": api_base,
        }
        kwargs.update(provider["extra_params"])
        if agent_model.max_tokens:
            kwargs["max_output_tokens"] = agent_model.max_tokens
        reasoning = self._responses_reasoning(agent_model)
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        # Runtime-owned native input/tools recomputed from the sanitized
        # counted originals always win over provider extras.
        self._reassert_runtime(
            kwargs, model=model_str, input_items=input_items, tools=responses_tools, stream=None
        )

        snapshot = await self._capture_rates(agent_model, provider)
        response, cap_ref = await capture_dispatch(
            "responses",
            kwargs,
            lambda **kw: asyncio.wait_for(
                self.transport.responses(**kw), timeout=settings.model_request_timeout
            ),
            rendered={"messages": messages, "tools": tools},
            tool_aliases=restore_map,
            attempt_metadata={
                "provider_id": agent_model.provider_id,
                "model_name": agent_model.name,
                "model_str": model_str,
            },
        )
        content, thinking, tool_calls = self._parse_response_output(response)
        (
            tokens_in,
            tokens_out,
            cached_tokens,
            thinking_tokens,
            cost,
            cost_source,
            cost_receipt,
        ) = self._apply_assessment(snapshot, response, "responses")
        return ScriptedResponse(
            tool_calls=self._restore_tool_names(tool_calls, restore_map),
            content=content,
            thinking=thinking,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost=cost,
            cost_source=cost_source,
            cost_receipt=cost_receipt,
            request_capture=cap_ref,
        )

    async def _complete_responses_stream(
        self,
        provider: dict[str, Any],
        agent_model: ModelConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ):
        model_str, api_base = self._route_model(provider, agent_model.name)
        sanitized_tools, restore_map = self._sanitize_tools(tools or [])
        input_items = self._responses_input(self._sanitize_messages(messages))
        responses_tools = self._responses_tools(sanitized_tools)
        kwargs: dict[str, Any] = {
            "model": model_str,
            "input": input_items,
            "api_key": provider["api_key"] or None,
            "api_base": api_base,
            "stream": True,
        }
        kwargs.update(provider["extra_params"])
        if agent_model.max_tokens:
            kwargs["max_output_tokens"] = agent_model.max_tokens
        reasoning = self._responses_reasoning(agent_model)
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        self._reassert_runtime(
            kwargs,
            model=model_str,
            input_items=input_items,
            tools=responses_tools,
            stream=True,
        )

        snapshot = await self._capture_rates(agent_model, provider)
        stream, cap_ref = await capture_dispatch(
            "responses_stream",
            kwargs,
            lambda **kw: asyncio.wait_for(
                self.transport.responses(**kw), timeout=settings.model_request_timeout
            ),
            rendered={"messages": messages, "tools": tools},
            tool_aliases=restore_map,
            attempt_metadata={
                "provider_id": agent_model.provider_id,
                "model_name": agent_model.name,
                "model_str": model_str,
            },
        )
        full_content = ""
        full_thinking = ""
        tool_calls: dict[str, dict[str, Any]] = {}
        tokens_in = tokens_out = 0
        cached_tokens: int | None = None
        thinking_tokens: int | None = None
        completed_response: Any = None
        async for event in stream:
            event_type = self._response_attr(event, "type", "")
            if event_type == "response.output_text.delta":
                text = self._response_attr(event, "delta", "") or ""
                full_content += text
                yield ("token", text)
            elif "reasoning" in event_type and event_type.endswith(".delta"):
                text = self._response_attr(event, "delta", "") or ""
                full_thinking += text
                yield ("thinking", text)
            elif event_type == "response.output_item.added":
                item = self._response_attr(event, "item")
                if self._response_attr(item, "type") == "function_call":
                    key = (
                        self._response_attr(item, "id")
                        or self._response_attr(item, "call_id")
                        or str(uuid.uuid4())
                    )
                    tool_calls[key] = {
                        "id": self._response_attr(item, "call_id") or key,
                        "name": self._response_attr(item, "name", ""),
                        "args": "",
                    }
            elif event_type == "response.function_call_arguments.delta":
                key = self._response_attr(event, "item_id", "")
                if key in tool_calls:
                    tool_calls[key]["args"] += self._response_attr(event, "delta", "") or ""
            elif event_type == "response.function_call_arguments.done":
                key = self._response_attr(event, "item_id", "")
                if key in tool_calls:
                    tool_calls[key]["args"] = self._response_attr(
                        event, "arguments", tool_calls[key]["args"]
                    )
            elif event_type == "response.completed":
                completed_response = self._response_attr(event, "response")

        parsed_tools = []
        for call in tool_calls.values():
            try:
                args = json.loads(call["args"] or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {}
            parsed_tools.append({"id": call["id"], "name": call["name"], "args": args})
        parsed_tools = self._restore_tool_names(parsed_tools, restore_map)
        (
            tokens_in,
            tokens_out,
            cached_tokens,
            thinking_tokens,
            cost,
            cost_source,
            cost_receipt,
        ) = self._apply_assessment(snapshot, completed_response, "responses")
        yield (
            "done",
            ScriptedResponse(
                tool_calls=parsed_tools,
                content=full_content,
                thinking=full_thinking,
                request_capture=cap_ref,
                # Reported usage wins — an explicit provider zero stays 0,
                # no char-estimate fallback.
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached_tokens=cached_tokens,
                thinking_tokens=thinking_tokens,
                cost=cost,
                cost_source=cost_source,
                cost_receipt=cost_receipt,
            ),
        )

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
    def _responses_reasoning(agent_model: ModelConfig) -> dict[str, str] | None:
        """Responses API reasoning params. When thinking is on, summary is
        required — without it the API reports reasoning tokens in usage but
        emits no reasoning deltas/items, so thinking never reaches the UI."""
        if agent_model.thinking_enabled is None:
            return None
        if not agent_model.thinking_enabled:
            return {"effort": "none"}
        return {
            "effort": agent_model.thinking_effort or "medium",
            "summary": "auto",
        }

    @staticmethod
    def _apply_thinking_kwargs(
        kwargs: dict[str, Any],
        agent_model: ModelConfig,
        provider: dict[str, Any],
        family: str | None = None,
    ) -> None:
        enabled = agent_model.thinking_enabled
        if enabled or enabled is False or (enabled is None and kwargs.get("tools")):
            effort = agent_model.thinking_effort or "medium" if enabled else "none"

            provider_type = provider.get("type", "")
            if provider_type == "openrouter":
                # OpenRouter uses `reasoning` in extra_body, not reasoning_effort
                extra = kwargs.get("extra_body", {})
                extra["reasoning"] = {"effort": effort}
                kwargs["extra_body"] = extra
            else:
                kwargs["reasoning_effort"] = effort

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
            try:
                return await self._complete_responses(provider, agent_model, messages, tools)
            except Exception as e:
                if not self._missing_on_responses(e):
                    raise
                log.info(
                    "model %s is not on the Responses API — falling back to chat completions",
                    agent_model.name,
                )
        orig_messages, orig_tools = messages, tools

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
        # Extras merged above may never replace the counted request —
        # runtime-owned model/messages/tools/stream win the merge.
        self._reassert_runtime(kwargs, model=model_str, messages=messages, tools=tools, stream=None)

        # Thinking/reasoning controls use the endpoint-specific field.
        family = self._model_family(provider, agent_model.name)
        self._apply_thinking_kwargs(kwargs, agent_model, provider, family)

        # Call LiteLLM — retry on the Responses API when the server says to
        # (reasoning models reject tools on chat completions).
        snapshot = await self._capture_rates(agent_model, provider)
        try:
            response, cap_ref = await capture_dispatch(
                "chat",
                kwargs,
                self.transport.completion,
                rendered={"messages": orig_messages, "tools": orig_tools},
                tool_aliases=restore_map,
                attempt_metadata={
                    "provider_id": agent_model.provider_id,
                    "model_name": agent_model.name,
                    "model_str": model_str,
                },
            )
        except Exception as e:
            if self._needs_responses_api(e):
                log.info(
                    "model %s requires the Responses API — retrying there",
                    agent_model.name,
                )
                return await self._complete_responses(
                    provider, agent_model, orig_messages, orig_tools
                )
            raise

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

        # Canonical usage + cost from the frozen pre-call rate snapshot —
        # SDK usage extractors and cost hints are never billing.
        (
            tokens_in,
            tokens_out,
            cached_tokens,
            thinking_tokens,
            cost,
            cost_source,
            cost_receipt,
        ) = self._apply_assessment(snapshot, response, "chat")

        content = message.content or ""

        return ScriptedResponse(
            tool_calls=tool_calls,
            content=content,
            thinking="",  # reasoning tokens handled separately if needed
            request_capture=cap_ref,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost=cost,
            cost_source=cost_source,
            cost_receipt=cost_receipt,
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
            try:
                async for event in self._complete_responses_stream(
                    provider, agent_model, messages, tools
                ):
                    yield event
                return
            except Exception as e:
                if not self._missing_on_responses(e):
                    raise
                log.info(
                    "model %s is not on the Responses API — falling back to chat completions",
                    agent_model.name,
                )
        orig_messages, orig_tools = messages, tools

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
        # Extras merged above may never replace the counted request —
        # runtime-owned model/messages/tools/stream win the merge.
        self._reassert_runtime(kwargs, model=model_str, messages=messages, tools=tools, stream=True)
        if kwargs.get("stream_options") != {"include_usage": True}:
            kwargs["stream_options"] = {"include_usage": True}

        # Call LiteLLM with streaming — retry on the Responses API when the
        # server says to (reasoning models reject tools on chat completions).
        snapshot = await self._capture_rates(agent_model, provider)
        try:
            stream, cap_ref = await capture_dispatch(
                "chat_stream",
                kwargs,
                lambda **kw: asyncio.wait_for(
                    self.transport.completion(**kw),
                    timeout=settings.model_request_timeout,
                ),
                rendered={"messages": orig_messages, "tools": orig_tools},
                tool_aliases=restore_map,
                attempt_metadata={
                    "provider_id": agent_model.provider_id,
                    "model_name": agent_model.name,
                    "model_str": model_str,
                },
            )
        except Exception as e:
            if self._needs_responses_api(e):
                log.info(
                    "model %s requires the Responses API — retrying there",
                    agent_model.name,
                )
                async for event in self._complete_responses_stream(
                    provider, agent_model, orig_messages, orig_tools
                ):
                    yield event
                return
            raise

        full_content = ""
        full_thinking = ""
        tool_calls_map: dict[int, dict[str, Any]] = {}
        tokens_in = 0
        tokens_out = 0
        cached_tokens: int | None = None
        thinking_tokens: int | None = None
        cost = 0.0
        usage_chunk: Any = None

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

            # Any usage-bearing chunk counts — providers send usage on the
            # final choices chunk too, not just dedicated usage frames.
            if getattr(chunk, "usage", None):
                usage_chunk = chunk
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Reasoning/thinking tokens (some models). Some providers populate
            # BOTH delta.reasoning_content and delta.reasoning with the same
            # text — so use elif to fall back, or every token is emitted twice.
            if getattr(delta, "reasoning_content", None):
                full_thinking += delta.reasoning_content
                yield ("thinking", delta.reasoning_content)
            elif getattr(delta, "reasoning", None):
                # Providers that put reasoning in delta.reasoning instead of
                # delta.reasoning_content (e.g. OpenAI Responses API bridge)
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

        # Canonical usage + cost from the frozen pre-call snapshot —
        # never stream.cost or cost_per_token. No usage chunk → assess the
        # stream object; the normalizer yields nulls, we don't guess.
        (
            tokens_in,
            tokens_out,
            cached_tokens,
            thinking_tokens,
            cost,
            cost_source,
            cost_receipt,
        ) = self._apply_assessment(
            snapshot, usage_chunk if usage_chunk is not None else stream, "chat"
        )
        cap_ref = getattr(stream, "request_capture", cap_ref)

        final = ScriptedResponse(
            tool_calls=tool_calls,
            content=full_content,
            thinking=full_thinking,
            request_capture=cap_ref,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost=cost,
            cost_source=cost_source,
            cost_receipt=cost_receipt,
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
