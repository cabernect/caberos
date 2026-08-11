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
from ..secret_store import decrypt

log = __import__("logging").getLogger("agentos.harness.litellm")
from .scripted_model import ScriptedResponse

# SSL certificate path for httpx — use the shared utility
from ..ssl_utils import SSL_CERT_PATH as _SSL_CERT

# Default base URLs for OpenAI-compatible providers (used when provider
# has no base_url configured, for live model discovery).
_DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together_ai": "https://api.together.xyz/v1",
    "fireworks_ai": "https://api.fireworks.ai/inference/v1",
    "perplexity": "https://api.perplexity.ai",
    "cohere": "https://api.cohere.com/v1",
    "ai21": "https://api.ai21.com/v1",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1",
    "huggingface": "https://api-inference.huggingface.co/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimax.chat/v1",
}


def _check_vision(model_id: str) -> bool:
    """Check if a model supports vision/image input via LiteLLM's model info.

    Tries multiple name variants since LiteLLM's catalog uses various naming
    conventions (e.g. "openrouter/google/gemma-3-27b", "google.gemma-3-27b-it",
    "gemini/gemma-3-27b-it") while our model names may use different separators
    or have a ":free" suffix.
    """
    info = _get_model_info_variants(model_id)
    return bool(info and info.get("supports_vision"))


def _check_thinking(model_id: str) -> dict[str, Any]:
    """Check if a model supports thinking/reasoning via LiteLLM's model info.

    Returns a dict with:
      - supports_thinking: bool
      - efforts: list of supported effort levels (e.g. ["low", "medium", "high"])
    """
    info = _get_model_info_variants(model_id)
    if not info:
        return {"supports_thinking": False, "efforts": []}

    supports = bool(info.get("supports_reasoning", False))
    efforts: list[str] = []
    # LiteLLM uses supports_<level>_reasoning_effort fields
    effort_map = {
        "minimal": "supports_minimal_reasoning_effort",
        "low": "supports_low_reasoning_effort",
        "medium": "supports_medium_reasoning_effort",
        "high": "supports_high_reasoning_effort",
        "xhigh": "supports_xhigh_reasoning_effort",
        "max": "supports_max_reasoning_effort",
    }
    for level, field in effort_map.items():
        val = info.get(field)
        if val:  # True or non-None
            efforts.append(level)

    # If no specific efforts listed but supports_reasoning, add default levels
    if supports and not efforts:
        efforts = ["low", "medium", "high"]

    return {"supports_thinking": supports, "efforts": efforts}


def _get_model_info_variants(model_id: str) -> dict[str, Any] | None:
    """Get LiteLLM model info, trying multiple name variants."""
    import litellm

    # Build a list of name variants to try
    candidates = [model_id]
    # Strip ":free" or other ":variant" suffixes
    base = model_id.split(":")[0]
    if base != model_id:
        candidates.append(base)
    # Try with common provider prefixes
    for prefix in ("openrouter/", "openai/", "anthropic/", "gemini/", "google/"):
        prefixed = f"{prefix}{base}"
        if prefixed not in candidates:
            candidates.append(prefixed)
    # Try replacing "google/" with "google." (LiteLLM uses dots for some Google models)
    if model_id.startswith("google/"):
        candidates.append(model_id.replace("google/", "google.", 1))
        candidates.append(base.replace("google/", "google.", 1))
    # Try just the model part (after the first /) with google. prefix
    if "/" in base:
        model_part = base.split("/", 1)[1]
        candidates.append(f"google.{model_part}")
        candidates.append(f"gemini/{model_part}")

    for name in candidates:
        try:
            info = litellm.get_model_info(name)
            if info:
                return info
        except Exception:
            pass
    return None


def _litellm_catalog(ptype: str) -> list[dict[str, Any]]:
    """Return LiteLLM's built-in model catalog for a provider type.

    LiteLLM ships `litellm.models_by_provider` — a dict mapping provider
    type → set of known model names. This is maintained by the LiteLLM
    team and updated with each release, so we get every provider's models
    for free (Anthropic, DeepSeek, xAI, Mistral, Groq, Cohere, etc.)
    without hand-maintaining static lists.
    """
    import litellm

    models = litellm.models_by_provider.get(ptype, set())
    result = []
    for m in sorted(models):
        thinking = _check_thinking(m)
        info = _get_model_info_variants(m)
        result.append({
            "id": m,
            "name": m,
            "supports_vision": _check_vision(m),
            "supports_thinking": thinking["supports_thinking"],
            "thinking_efforts": thinking["efforts"],
            "max_context_tokens": info.get("max_input_tokens") if info else None,
            "max_output_tokens": info.get("max_output_tokens") if info else None,
        })
    return result


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
        return [
            {**tc, "name": restore_map.get(tc["name"], tc["name"])} for tc in tool_calls
        ]

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
        model_str = f"{provider['type']}/{agent_model.name}"
        return {
            "model_str": model_str,
            "api_key": provider["api_key"] or None,
            "base_url": provider["base_url"] or None,
        }

    @staticmethod
    def _apply_thinking_kwargs(kwargs: dict[str, Any], agent_model: ModelConfig) -> None:
        """Apply thinking/reasoning parameters to LiteLLM kwargs.

        LiteLLM supports thinking via:
        - Anthropic: thinking={"type": "enabled"/"disabled", "budget_tokens": N}
        - OpenAI o-series: reasoning_effort="low"/"medium"/"high"
        - OpenRouter: reasoning={"effort": "low"/"medium"/"high", "exclude": bool}
        - DeepSeek: thinking={"type": "enabled"/"disabled"}

        We set the common params and let LiteLLM route them per provider.
        """
        if agent_model.thinking_enabled is None:
            return  # use model default

        if agent_model.thinking_enabled:
            effort = agent_model.thinking_effort or "medium"
            # OpenAI o-series style
            kwargs["reasoning_effort"] = effort
            # Anthropic style — enable thinking with a budget based on effort
            effort_budgets = {"low": 5000, "medium": 16000, "high": 32000, "max": 64000, "xhigh": 64000}
            budget = effort_budgets.get(effort, 16000)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # OpenRouter style
            kwargs.setdefault("extra_body", {})["reasoning"] = {"effort": effort}
        else:
            # Disable thinking explicitly
            kwargs["reasoning_effort"] = "none"
            kwargs["thinking"] = {"type": "disabled"}
            kwargs.setdefault("extra_body", {})["reasoning"] = {"exclude": True}

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

        # Build the LiteLLM model string: "provider_type/model_name"
        # LiteLLM uses prefixes like "openai/gpt-4o", "anthropic/claude-3-5-sonnet",
        # "gemini/gemini-1.5-flash", "ollama/llama3"
        model_str = f"{provider['type']}/{agent_model.name}"

        kwargs: dict[str, Any] = {
            "model": model_str,
            "messages": messages,
        }

        # Provider-specific params
        if provider["api_key"]:
            kwargs["api_key"] = provider["api_key"]
        if provider["base_url"]:
            kwargs["api_base"] = provider["base_url"]
        if provider["org_id"]:
            kwargs["organization"] = provider["org_id"]
        kwargs.update(provider["extra_params"])

        if agent_model.max_tokens:
            kwargs["max_tokens"] = agent_model.max_tokens

        # Thinking/reasoning controls
        self._apply_thinking_kwargs(kwargs, agent_model)

        # Tools are already in OpenAI format: {"type": "function", "function": {...}}
        # Sanitize tool names for providers that reject dots (e.g. OpenAI-compatible)
        restore_map: dict[str, str] = {}
        if tools:
            tools, restore_map = self._sanitize_tools(tools)
            kwargs["tools"] = tools
        # Sanitize tool names in message history too
        messages = self._sanitize_messages(messages)

        # Call LiteLLM
        response = await litellm.acompletion(**kwargs)

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

        # LiteLLM provides cost via response._hidden_params or response.cost
        cost = 0.0
        try:
            cost = float(response.cost) if hasattr(response, "cost") and response.cost else 0.0
        except (TypeError, ValueError):
            cost = 0.0

        content = message.content or ""

        return ScriptedResponse(
            tool_calls=tool_calls,
            content=content,
            thinking="",  # reasoning tokens handled separately if needed
            tokens_in=tokens_in,
            tokens_out=tokens_out,
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
        model_str = f"{provider['type']}/{agent_model.name}"

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
        if provider["base_url"]:
            kwargs["api_base"] = provider["base_url"]
        if provider["org_id"]:
            kwargs["organization"] = provider["org_id"]
        kwargs.update(provider["extra_params"])

        if agent_model.max_tokens:
            kwargs["max_tokens"] = agent_model.max_tokens

        # Thinking/reasoning controls
        self._apply_thinking_kwargs(kwargs, agent_model)

        if tools:
            # Tools are already in OpenAI format
            kwargs["tools"] = tools

        # Request usage info in streaming responses (OpenAI-compatible)
        kwargs["stream_options"] = {"include_usage": True}

        # Call LiteLLM with streaming
        stream = await asyncio.wait_for(
            litellm.acompletion(**kwargs), timeout=settings.model_request_timeout
        )

        full_content = ""
        full_thinking = ""
        tool_calls_map: dict[int, dict[str, Any]] = {}
        tokens_in = 0
        tokens_out = 0
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
                continue

            delta = chunk.choices[0].delta

            # Reasoning/thinking tokens (some models)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                full_thinking += delta.reasoning_content
                yield ("thinking", delta.reasoning_content)

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

        # Get cost from the stream's hidden params
        try:
            cost = float(stream.cost) if hasattr(stream, "cost") and stream.cost else 0.0
        except (TypeError, ValueError):
            cost = 0.0

        # If we didn't get usage from streaming, estimate
        if tokens_in == 0:
            tokens_in = sum(len(m.get("content", "")) for m in messages) // 4
        if tokens_out == 0:
            tokens_out = (len(full_content) + len(full_thinking)) // 4

        final = ScriptedResponse(
            tool_calls=tool_calls,
            content=full_content,
            thinking=full_thinking,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
        )
        yield ("done", final)

    async def validate_model(self, provider_id: str, model_name: str) -> bool:
        """Cheap 1-token completion to validate the model config at save time."""
        provider = await self._load_provider(provider_id)
        model_str = f"{provider['type']}/{model_name}"

        kwargs: dict[str, Any] = {
            "model": model_str,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }
        if provider["api_key"]:
            kwargs["api_key"] = provider["api_key"]
        if provider["base_url"]:
            kwargs["api_base"] = provider["base_url"]
        kwargs.update(provider["extra_params"])

        await litellm.acompletion(**kwargs)
        return True

    async def discover_models(self, provider_id: str) -> list[dict[str, Any]]:
        """List available models for a provider (dynamic discovery, D40).

        Strategy:
        1. Providers with a known list API (OpenAI, Gemini, Ollama, OpenRouter)
           → live discovery (returns only models the API key can access).
        2. Other providers → LiteLLM's built-in catalog
           (`litellm.models_by_provider`), which covers 60+ providers
           and is maintained by the LiteLLM team.
        3. Live discovery is also attempted for OpenAI-compatible providers
           that have a base_url set; if it fails, falls back to LiteLLM catalog.
        4. Unknown provider types → empty list (free-text fallback in UI).
        """
        provider = await self._load_provider(provider_id)
        ptype = provider["type"]

        if ptype == "openai":
            return await self._discover_openai(provider)
        elif ptype == "gemini" or ptype == "google":
            return await self._discover_gemini(provider)
        elif ptype == "ollama":
            return await self._discover_ollama(provider)
        elif ptype == "openrouter":
            return await self._discover_openrouter(provider)
        elif ptype == "anthropic":
            models = await self._discover_anthropic(provider)
            if models:
                return models
            return _litellm_catalog(ptype)
        elif ptype in _DEFAULT_BASE_URLS:
            # Try live /v1/models first, fall back to LiteLLM catalog
            models = await self._discover_openai_compat(provider, ptype)
            if models:
                return models
            return _litellm_catalog(ptype)
        else:
            # All other known providers: LiteLLM catalog
            return _litellm_catalog(ptype)

    async def _discover_openai_compat(
        self, provider: dict[str, Any], ptype: str
    ) -> list[dict[str, Any]]:
        """Try OpenAI-compatible /v1/models endpoint for providers like
        DeepSeek, xAI, Mistral, Groq, Together, Fireworks, etc."""
        try:
            import httpx

            # Build the default base URL for this provider type
            default_base = _DEFAULT_BASE_URLS.get(ptype, "")
            base = provider["base_url"] or default_base
            if not base:
                return []

            headers = {}
            if provider["api_key"]:
                headers["Authorization"] = f"Bearer {provider['api_key']}"

            async with httpx.AsyncClient(verify=_SSL_CERT) as client:
                resp = await client.get(f"{base}/models", headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                result = []
                for m in data.get("data", []):
                    thinking = _check_thinking(m["id"])
                    info = _get_model_info_variants(m["id"])
                    result.append({
                        "id": m["id"],
                        "name": m["id"],
                        "supports_vision": _check_vision(m["id"]),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": info.get("max_input_tokens") if info else None,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    })
                return result
        except Exception:
            return []

    async def _discover_anthropic(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        """Anthropic's /v1/models API returns capabilities (vision, thinking, etc.)."""
        try:
            import httpx

            base = provider["base_url"] or "https://api.anthropic.com"
            headers = {
                "x-api-key": provider["api_key"],
                "anthropic-version": "2023-06-01",
            }
            models: list[dict[str, Any]] = []
            after_id = None
            # Paginate — Anthropic returns up to 1000 per page
            for _ in range(10):  # safety limit
                url = f"{base}/v1/models?limit=1000"
                if after_id:
                    url += f"&after_id={after_id}"
                async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                for m in data.get("data", []):
                    caps = m.get("capabilities", {})
                    supports_vision = caps.get("image_input", {}).get("supported", False)
                    thinking_caps = caps.get("thinking", {})
                    supports_thinking = thinking_caps.get("supported", False)
                    # Anthropic thinking types: adaptive, enabled
                    thinking_types = thinking_caps.get("types", {})
                    efforts = []
                    if thinking_types.get("adaptive", {}).get("supported"):
                        efforts.append("adaptive")
                    if thinking_types.get("enabled", {}).get("supported"):
                        efforts.extend(["low", "medium", "high"])
                    if supports_thinking and not efforts:
                        efforts = ["low", "medium", "high"]
                    models.append({
                        "id": m["id"],
                        "name": m.get("display_name", m["id"]),
                        "supports_vision": supports_vision,
                        "supports_thinking": supports_thinking,
                        "thinking_efforts": efforts,
                        "max_context_tokens": m.get("max_input_tokens") or None,
                        "max_output_tokens": m.get("max_tokens") or None,
                    })
                if not data.get("has_more"):
                    break
                after_id = data.get("last_id")
                if not after_id:
                    break
            log.info("Discovered %d Anthropic models", len(models))
            return models
        except Exception as e:
            log.exception("Anthropic model discovery failed: %s", e)
            return []

    async def _discover_openrouter(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        """OpenRouter has a public /api/v1/models endpoint.

        OpenRouter's response includes architecture.input_modalities, which we
        use for vision detection instead of LiteLLM's static catalog (which
        doesn't cover many OpenRouter models).
        """
        try:
            import httpx

            base = provider["base_url"] or "https://openrouter.ai/api/v1"
            headers = {}
            if provider["api_key"]:
                headers["Authorization"] = f"Bearer {provider['api_key']}"
            log.warning("Discovering OpenRouter models from %s (cert=%s)", base, _SSL_CERT)
            async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
                resp = await client.get(f"{base}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                models = []
                for m in data.get("data", []):
                    arch = m.get("architecture", {})
                    # Skip image-generation models (text→image) — not useful for chat.
                    # Keep router models like openrouter/auto which can also output images.
                    output_modalities = arch.get("output_modalities", []) or []
                    if "image" in output_modalities and not m["id"].startswith("openrouter/"):
                        continue
                    # Use OpenRouter's modality metadata when available — more
                    # accurate than LiteLLM's static catalog for OpenRouter models
                    input_modalities = arch.get("input_modalities", [])
                    if "image" in input_modalities or "video" in input_modalities:
                        supports_vision = True
                    elif input_modalities:  # modalities listed but no image/video
                        supports_vision = False
                    else:
                        # Fallback to LiteLLM catalog if OpenRouter doesn't provide modality info
                        supports_vision = _check_vision(m["id"])
                    # Thinking/reasoning support from OpenRouter's reasoning field
                    reasoning = m.get("reasoning", {})
                    supports_thinking = reasoning is not None
                    # OpenRouter supports_efforts list, or infer from reasoning presence
                    efforts = reasoning.get("supported_efforts", []) if reasoning else []
                    if supports_thinking and not efforts:
                        # If reasoning is present but no efforts listed, use defaults
                        efforts = ["low", "medium", "high"]
                    # Fallback to LiteLLM catalog for thinking info
                    if not supports_thinking:
                        thinking_info = _check_thinking(m["id"])
                        supports_thinking = thinking_info["supports_thinking"]
                        efforts = thinking_info["efforts"]
                    models.append({
                        "id": m["id"],
                        "name": m["id"],
                        "supports_vision": supports_vision,
                        "supports_thinking": supports_thinking,
                        "thinking_efforts": efforts,
                        "max_context_tokens": m.get("context_length"),
                        "max_output_tokens": m.get("top_provider", {}).get("max_completion_tokens"),
                    })
                log.info("Discovered %d OpenRouter models", len(models))
                return models
        except Exception as e:
            log.exception("OpenRouter model discovery failed: %s", e)
            return []

    async def _discover_openai(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            headers = {"Authorization": f"Bearer {provider['api_key']}"}
            if provider["org_id"]:
                headers["OpenAI-Organization"] = provider["org_id"]

            base = provider["base_url"] or "https://api.openai.com/v1"
            async with httpx.AsyncClient(verify=_SSL_CERT) as client:
                resp = await client.get(f"{base}/models", headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                result = []
                for m in data.get("data", []):
                    thinking = _check_thinking(m["id"])
                    info = _get_model_info_variants(m["id"])
                    result.append({
                        "id": m["id"],
                        "name": m["id"],
                        "supports_vision": _check_vision(m["id"]),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": info.get("max_input_tokens") if info else None,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    })
                return result
        except Exception:
            return []

    async def _discover_gemini(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            base = provider["base_url"] or "https://generativelanguage.googleapis.com/v1beta"
            url = f"{base}/models?key={provider['api_key']}"
            async with httpx.AsyncClient(verify=_SSL_CERT) as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                result = []
                for m in data.get("models", []):
                    mid = m["name"].replace("models/", "")
                    thinking = _check_thinking(mid)
                    info = _get_model_info_variants(mid)
                    result.append({
                        "id": mid,
                        "name": m.get("displayName", m["name"]),
                        "supports_vision": _check_vision(mid),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": info.get("max_input_tokens") if info else None,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    })
                return result
        except Exception:
            return []

    async def _discover_ollama(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            base = provider["base_url"] or "http://localhost:11434"
            async with httpx.AsyncClient(verify=_SSL_CERT) as client:
                resp = await client.get(f"{base}/api/tags", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                result = []
                for m in data.get("models", []):
                    thinking = _check_thinking(m["name"])
                    info = _get_model_info_variants(m["name"])
                    result.append({
                        "id": m["name"],
                        "name": m["name"],
                        "supports_vision": _check_vision(m["name"]),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": info.get("max_input_tokens") if info else None,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    })
                return result
        except Exception:
            return []
