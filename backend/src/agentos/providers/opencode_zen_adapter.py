"""OpenCode Zen protocol routing on top of LiteLLM."""

import asyncio
import json
import uuid
from typing import Any

from ..config import settings
from ..config_schema import ModelConfig
from ..harness.scripted_model import ScriptedResponse


class OpenCodeZenMixin:
    """OpenCode Zen routing, reasoning fields, and Responses parsing.

    This mixin is combined with the generic LiteLLM adapter so the transport
    remains LiteLLM while Zen-specific protocol behavior stays local.
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
                        "output": OpenCodeZenMixin._responses_tool_output(
                            message.get("content", "")
                        ),
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
                arguments = cls._response_attr(item, "arguments", "{}") or "{}"
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

    @classmethod
    def _response_usage(cls, response: Any) -> tuple[int, int, int | None]:
        usage = cls._response_attr(response, "usage")
        details = cls._response_attr(usage, "input_tokens_details")
        cached = cls._response_attr(details, "cached_tokens")
        if cached is None:
            cached = cls._response_attr(usage, "cached_tokens")
        return (
            int(cls._response_attr(usage, "input_tokens", 0) or 0),
            int(cls._response_attr(usage, "output_tokens", 0) or 0),
            int(cached) if cached is not None else None,
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
        kwargs: dict[str, Any] = {
            "model": model_str,
            "input": self._responses_input(sanitized_messages),
            "api_key": provider["api_key"] or None,
            "api_base": api_base,
        }
        if agent_model.max_tokens:
            kwargs["max_output_tokens"] = agent_model.max_tokens
        responses_tools = self._responses_tools(sanitized_tools)
        if responses_tools:
            kwargs["tools"] = responses_tools
        if agent_model.thinking_enabled is not None:
            kwargs["reasoning"] = {
                "effort": (
                    agent_model.thinking_effort or "medium"
                    if agent_model.thinking_enabled
                    else "none"
                )
            }

        response = await asyncio.wait_for(
            self.transport.responses(**kwargs), timeout=settings.model_request_timeout
        )
        content, thinking, tool_calls = self._parse_response_output(response)
        tokens_in, tokens_out, cached_tokens = self._response_usage(response)
        return ScriptedResponse(
            tool_calls=self._restore_tool_names(tool_calls, restore_map),
            content=content,
            thinking=thinking,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_tokens=cached_tokens,
            cost=float(getattr(response, "cost", 0.0) or 0.0),
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
        kwargs: dict[str, Any] = {
            "model": model_str,
            "input": self._responses_input(self._sanitize_messages(messages)),
            "api_key": provider["api_key"] or None,
            "api_base": api_base,
            "stream": True,
        }
        if agent_model.max_tokens:
            kwargs["max_output_tokens"] = agent_model.max_tokens
        responses_tools = self._responses_tools(sanitized_tools)
        if responses_tools:
            kwargs["tools"] = responses_tools
        if agent_model.thinking_enabled is not None:
            kwargs["reasoning"] = {
                "effort": (
                    agent_model.thinking_effort or "medium"
                    if agent_model.thinking_enabled
                    else "none"
                )
            }

        stream = await asyncio.wait_for(
            self.transport.responses(**kwargs), timeout=settings.model_request_timeout
        )
        full_content = ""
        full_thinking = ""
        tool_calls: dict[str, dict[str, Any]] = {}
        tokens_in = tokens_out = 0
        cached_tokens: int | None = None
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
                response = self._response_attr(event, "response")
                tokens_in, tokens_out, cached_tokens = self._response_usage(response)

        parsed_tools = []
        for call in tool_calls.values():
            try:
                args = json.loads(call["args"] or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {}
            parsed_tools.append({"id": call["id"], "name": call["name"], "args": args})
        parsed_tools = self._restore_tool_names(parsed_tools, restore_map)
        yield (
            "done",
            ScriptedResponse(
                tool_calls=parsed_tools,
                content=full_content,
                thinking=full_thinking,
                tokens_in=tokens_in or sum(len(str(m.get("content", ""))) for m in messages) // 4,
                tokens_out=tokens_out or (len(full_content) + len(full_thinking)) // 4,
                cached_tokens=cached_tokens,
                cost=0.0,
            ),
        )
