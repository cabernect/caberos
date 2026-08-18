"""Model discovery and validation backed by LiteLLM/provider APIs."""

from typing import Any

import litellm

from ..ssl_utils import SSL_CERT_PATH as _SSL_CERT

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


def _get_model_info_variants(model_id: str) -> dict[str, Any] | None:
    """Get LiteLLM model info, trying common provider name variants."""
    candidates = [model_id]
    base = model_id.split(":")[0]
    if base != model_id:
        candidates.append(base)
    for prefix in ("openrouter/", "openai/", "anthropic/", "gemini/", "google/"):
        prefixed = f"{prefix}{base}"
        if prefixed not in candidates:
            candidates.append(prefixed)
    if model_id.startswith("google/"):
        candidates.append(model_id.replace("google/", "google.", 1))
        candidates.append(base.replace("google/", "google.", 1))
    if "/" in base:
        model_part = base.split("/", 1)[1]
        candidates.extend([f"google.{model_part}", f"gemini/{model_part}"])

    for name in candidates:
        try:
            info = litellm.get_model_info(name)
            if info:
                return info
        except Exception:
            pass
    return None


def _check_vision(model_id: str) -> bool:
    info = _get_model_info_variants(model_id)
    return bool(info and info.get("supports_vision"))


def _check_thinking(model_id: str) -> dict[str, Any]:
    info = _get_model_info_variants(model_id)
    if not info:
        return {"supports_thinking": False, "efforts": []}
    supports = bool(info.get("supports_reasoning", False))
    effort_map = {
        "none": "supports_none_reasoning_effort",
        "minimal": "supports_minimal_reasoning_effort",
        "low": "supports_low_reasoning_effort",
        "medium": "supports_medium_reasoning_effort",
        "high": "supports_high_reasoning_effort",
        "xhigh": "supports_xhigh_reasoning_effort",
        "max": "supports_max_reasoning_effort",
    }
    efforts = [
        level
        for level, field_name in effort_map.items()
        if info.get(field_name) is True or (info.get(field_name) is None and supports)
    ]
    if supports and not efforts:
        efforts = ["low", "medium", "high"]
    return {"supports_thinking": supports, "efforts": efforts}


def _check_capabilities(model_id: str) -> dict[str, Any]:
    thinking = _check_thinking(model_id)
    info = _get_model_info_variants(model_id)
    if info:
        return {
            "supports_vision": _check_vision(model_id),
            "supports_thinking": thinking["supports_thinking"],
            "thinking_efforts": thinking["efforts"],
            "max_context_tokens": info.get("max_input_tokens") or 200000,
            "max_output_tokens": info.get("max_output_tokens"),
        }
    name = model_id.lower()
    return {
        "supports_vision": any(
            pattern in name
            for pattern in (
                "vision",
                "gpt-4o",
                "gpt-4.1",
                "gpt-4.5",
                "gpt-5",
                "claude-3",
                "claude-4",
                "gemini",
                "llava",
                "qwen-vl",
                "o1",
                "o3",
                "o4",
            )
        ),
        "supports_thinking": thinking["supports_thinking"],
        "thinking_efforts": thinking["efforts"],
        "max_context_tokens": 200000,
        "max_output_tokens": None,
    }


def _litellm_catalog(ptype: str) -> list[dict[str, Any]]:
    models = litellm.models_by_provider.get(ptype, set())
    return [
        {
            "id": model_id,
            "name": model_id,
            **_check_capabilities(model_id),
        }
        for model_id in sorted(models)
        if _is_chat_model(model_id)
    ]


# --- Chat model filtering ---
#
# Providers return ALL models (embeddings, TTS, STT, image gen, moderation).
# We only want text-in → text-out chat models. Filter by known non-chat
# name patterns and by LiteLLM metadata when available.

_NON_CHAT_PATTERNS: tuple[str, ...] = (
    "embedding",
    "embed",
    "whisper",
    "tts",
    "speech",
    "transcribe",
    "dall-e",
    "gpt-image",
    "chatgpt-image",
    "search-api",
    "davinci",  # legacy completion-only (no chat)
    "babbage",  # legacy completion-only
    "ada-002",  # embedding
    "moderation",
    "text-moderation",
    "audio",
    "realtime",
    "sora",
)


def _is_chat_model(model_id: str) -> bool:
    """Return True if the model supports text-in → text-out chat."""
    name = model_id.lower()

    # Fast path: known non-chat patterns
    for pattern in _NON_CHAT_PATTERNS:
        if pattern in name:
            return False

    # Check LiteLLM metadata — if it explicitly says the model is not a chat
    # model (e.g. mode is "embedding" or "completion"), filter it out.
    info = _get_model_info_variants(model_id)
    if info:
        mode = info.get("mode", "")
        if mode in ("embedding", "completion"):
            return False

    return True


class LiteLLMModelCatalog:
    """Discovery and validation implementation for a LiteLLM adapter."""

    def __init__(self, adapter: Any):
        self.adapter = adapter

    async def validate_model(self, provider_id: str, model_name: str) -> bool:
        """Cheap 1-token completion to validate the model config at save time."""
        provider = await self.adapter._load_provider(provider_id)
        model_str, api_base = self.adapter._route_model(provider, model_name)

        kwargs: dict[str, Any] = {
            "model": model_str,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }
        if provider["api_key"]:
            kwargs["api_key"] = provider["api_key"]
        if api_base or provider["base_url"]:
            kwargs["api_base"] = api_base or provider["base_url"]
        kwargs.update(provider["extra_params"])

        await self.adapter.transport.completion(**kwargs)
        return True

    async def discover_models(self, provider_id: str) -> list[dict[str, Any]]:
        """Discover models live first, then fall back to LiteLLM's catalog."""
        provider = await self.adapter._load_provider(provider_id)
        ptype = provider["type"]

        live_models: list[dict[str, Any]] = []
        if ptype == "openai":
            live_models = await self._discover_openai(provider)
        elif ptype in ("gemini", "google"):
            live_models = await self._discover_gemini(provider)
        elif ptype == "ollama":
            live_models = await self._discover_ollama(provider)
        elif ptype == "openrouter":
            live_models = await self._discover_openrouter(provider)
        elif ptype == "anthropic":
            live_models = await self._discover_anthropic(provider)
        elif ptype in _DEFAULT_BASE_URLS or provider.get("base_url"):
            live_models = await self._discover_openai_compat(provider, ptype)

        return live_models or _litellm_catalog(ptype)

    async def _discover_openai_compat(
        self, provider: dict[str, Any], ptype: str
    ) -> list[dict[str, Any]]:
        """Try an OpenAI-compatible /models endpoint."""
        try:
            import httpx

            base = provider["base_url"] or _DEFAULT_BASE_URLS.get(ptype, "")
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
            for model in data.get("data", []):
                model_id = model["id"]
                if not _is_chat_model(model_id):
                    continue
                thinking = _check_thinking(model_id)
                info = _get_model_info_variants(model_id)
                result.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "supports_vision": _check_vision(model_id),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": (info.get("max_input_tokens") if info else None)
                        or 200000,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    }
                )
            return result
        except Exception:
            return []

    async def _discover_anthropic(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover models and capabilities from Anthropic's models API."""
        try:
            import httpx

            base = provider["base_url"] or "https://api.anthropic.com"
            headers = {
                "x-api-key": provider["api_key"],
                "anthropic-version": "2023-06-01",
            }
            models: list[dict[str, Any]] = []
            after_id = None
            for _ in range(10):
                url = f"{base}/v1/models?limit=1000"
                if after_id:
                    url += f"&after_id={after_id}"
                async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                for model in data.get("data", []):
                    capabilities = model.get("capabilities", {})
                    supports_vision = capabilities.get("image_input", {}).get("supported", False)
                    thinking_caps = capabilities.get("thinking", {})
                    supports_thinking = thinking_caps.get("supported", False)
                    thinking_types = thinking_caps.get("types", {})
                    efforts = []
                    if thinking_types.get("adaptive", {}).get("supported"):
                        efforts.append("adaptive")
                    if thinking_types.get("enabled", {}).get("supported"):
                        efforts.extend(["low", "medium", "high"])
                    if supports_thinking and not efforts:
                        efforts = ["low", "medium", "high"]
                    models.append(
                        {
                            "id": model["id"],
                            "name": model.get("display_name", model["id"]),
                            "supports_vision": supports_vision,
                            "supports_thinking": supports_thinking,
                            "thinking_efforts": efforts,
                            "max_context_tokens": model.get("max_input_tokens") or 200000,
                            "max_output_tokens": model.get("max_tokens") or None,
                        }
                    )
                if not data.get("has_more"):
                    break
                after_id = data.get("last_id")
                if not after_id:
                    break
            return models
        except Exception:
            return []

    async def _discover_openrouter(self, provider: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover OpenRouter models using its modality metadata."""
        try:
            import httpx

            base = provider["base_url"] or "https://openrouter.ai/api/v1"
            headers = {}
            if provider["api_key"]:
                headers["Authorization"] = f"Bearer {provider['api_key']}"
            async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CERT) as client:
                resp = await client.get(f"{base}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
            models = []
            for model in data.get("data", []):
                model_id = model["id"]
                if not _is_chat_model(model_id):
                    continue
                architecture = model.get("architecture", {})
                output_modalities = architecture.get("output_modalities", []) or []
                if "image" in output_modalities and not model_id.startswith("openrouter/"):
                    continue
                input_modalities = architecture.get("input_modalities", [])
                if "image" in input_modalities or "video" in input_modalities:
                    supports_vision = True
                elif input_modalities:
                    supports_vision = False
                else:
                    supports_vision = _check_vision(model["id"])
                reasoning = model.get("reasoning", {})
                supports_thinking = reasoning is not None
                efforts = reasoning.get("supported_efforts", []) if reasoning else []
                if supports_thinking and not efforts:
                    efforts = ["low", "medium", "high"]
                if not supports_thinking:
                    thinking_info = _check_thinking(model["id"])
                    supports_thinking = thinking_info["supports_thinking"]
                    efforts = thinking_info["efforts"]
                models.append(
                    {
                        "id": model["id"],
                        "name": model["id"],
                        "supports_vision": supports_vision,
                        "supports_thinking": supports_thinking,
                        "thinking_efforts": efforts,
                        "max_context_tokens": model.get("context_length") or 200000,
                        "max_output_tokens": model.get("top_provider", {}).get(
                            "max_completion_tokens"
                        ),
                    }
                )
            return models
        except Exception:
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
            for model in data.get("data", []):
                model_id = model["id"]
                if not _is_chat_model(model_id):
                    continue
                thinking = _check_thinking(model_id)
                info = _get_model_info_variants(model_id)
                result.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "supports_vision": _check_vision(model_id),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": (info.get("max_input_tokens") if info else None)
                        or 200000,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    }
                )
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
            for model in data.get("models", []):
                model_id = model["name"].replace("models/", "")
                if not _is_chat_model(model_id):
                    continue
                thinking = _check_thinking(model_id)
                info = _get_model_info_variants(model_id)
                result.append(
                    {
                        "id": model_id,
                        "name": model.get("displayName", model["name"]),
                        "supports_vision": _check_vision(model_id),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": (info.get("max_input_tokens") if info else None)
                        or 200000,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    }
                )
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
            for model in data.get("models", []):
                model_id = model["name"]
                if not _is_chat_model(model_id):
                    continue
                thinking = _check_thinking(model_id)
                info = _get_model_info_variants(model_id)
                result.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "supports_vision": _check_vision(model_id),
                        "supports_thinking": thinking["supports_thinking"],
                        "thinking_efforts": thinking["efforts"],
                        "max_context_tokens": (info.get("max_input_tokens") if info else None)
                        or 200000,
                        "max_output_tokens": info.get("max_output_tokens") if info else None,
                    }
                )
            return result
        except Exception:
            return []
