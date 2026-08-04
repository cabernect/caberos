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
from .scripted_model import ScriptedResponse


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

        # Tools are already in OpenAI format: {"type": "function", "function": {...}}
        if tools:
            kwargs["tools"] = tools

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

        # DEBUG: print message roles
        import sys as _sys

        print("[DEBUG stream] messages:", file=_sys.stderr)
        for i, m in enumerate(messages):
            tc = bool(m.get("tool_calls"))
            print(
                f"  {i}: role={m['role']} tool_calls={tc} content={str(m.get('content', ''))[:60]}",
                file=_sys.stderr,
            )

        provider = await self._load_provider(agent_model.provider_id)
        model_str = f"{provider['type']}/{agent_model.name}"

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
        """List available models for a provider (dynamic discovery, D40)."""
        provider = await self._load_provider(provider_id)
        ptype = provider["type"]

        if ptype == "openai":
            return await self._discover_openai(provider)
        elif ptype == "gemini" or ptype == "google":
            return await self._discover_gemini(provider)
        elif ptype == "ollama":
            return await self._discover_ollama(provider)
        else:
            # Anthropic and others: no list endpoint, free-text fallback
            return []

    async def _discover_openai(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            headers = {"Authorization": f"Bearer {provider['api_key']}"}
            if provider["org_id"]:
                headers["OpenAI-Organization"] = provider["org_id"]

            base = provider["base_url"] or "https://api.openai.com/v1"
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base}/models", headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return [{"id": m["id"], "name": m["id"]} for m in data.get("data", [])]
        except Exception:
            return []

    async def _discover_gemini(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            base = provider["base_url"] or "https://generativelanguage.googleapis.com/v1beta"
            url = f"{base}/models?key={provider['api_key']}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "id": m["name"].replace("models/", ""),
                        "name": m.get("displayName", m["name"]),
                    }
                    for m in data.get("models", [])
                ]
        except Exception:
            return []

    async def _discover_ollama(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import httpx

            base = provider["base_url"] or "http://localhost:11434"
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base}/api/tags", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return [{"id": m["name"], "name": m["name"]} for m in data.get("models", [])]
        except Exception:
            return []
