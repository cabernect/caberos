"""Context assembly (D35 — order: base prompt, soul, persona, task, MEMORY.md, skills, KG, turns, recall).

The base system prompt (platform-level operating instructions) is always loaded
first, before the agent's identity. This tells the agent how to work inside
CaberOS regardless of its soul/persona/task.
"""

from typing import Any

from ..config_schema import AgentConfig
from ..models.run import Message
from .base_prompt import get_base_system_prompt


def assemble_system_prompt(agent_config: AgentConfig) -> str:
    """Build the system prompt from base prompt + agent identity (D35 order).

    Order:
    1. Base system prompt (platform instructions — same for every agent)
    2. Soul (who the agent is — values, principles)
    3. Persona (how the agent communicates — tone, style)
    4. Task (what the agent does — mission, instructions)
    5. MEMORY.md (long-term memory — loaded in ticket 06)
    6. Skills (prompt injection — loaded in ticket 06)
    7. KG facts (knowledge graph — loaded in ticket 06)
    """
    parts: list[str] = []

    # 1. Base system prompt — always first, same for every agent
    parts.append(get_base_system_prompt())

    # 2-4. Agent identity (D35)
    if agent_config.soul:
        parts.append(f"## Soul\n\n{agent_config.soul}")

    if agent_config.persona:
        parts.append(f"## Persona\n\n{agent_config.persona}")

    if agent_config.task:
        parts.append(f"## Task\n\n{agent_config.task}")

    # MEMORY.md loading will be added in ticket 06
    # Skills loading will be added in ticket 06
    # KG facts will be added in ticket 06

    return "\n\n---\n\n".join(parts)


def assemble_tool_schemas(agent_config: AgentConfig) -> list[dict[str, Any]]:
    """Build tool schemas from the agent's granted capabilities."""
    from ..capabilities.registry import registry

    schemas: list[dict[str, Any]] = []
    for grant in agent_config.capabilities:
        cap = registry.get(grant.name)
        if cap is None:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": cap.name,
                    "description": cap.description,
                    "parameters": cap.parameters_schema,
                },
            }
        )
    return schemas


def build_message_history(
    system_prompt: str,
    recent_messages: list[Message],
    user_message: str,
    attachments: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the message history for the model call.

    When attachments are present (images, URLs), the user message is built as a
    multimodal content array (OpenAI/LiteLLM format):
        [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]

    When no attachments, the user message is a plain string (saves tokens).
    """
    history: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    for msg in recent_messages:
        history.append({"role": msg.role, "content": msg.content})

    # Build the user message — multimodal if attachments are present
    if attachments:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        for att in attachments:
            if att.type == "image":
                # base64 data URI — model sees the image directly
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{att.mime_type};base64,{att.data}"},
                })
            elif att.type == "url":
                # URL — model fetches and processes it
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": att.data},
                })
            elif att.type == "file":
                # Text file — append content to the message text
                if att.mime_type.startswith("text/") or att.mime_type == "application/json":
                    content_parts.append({
                        "type": "text",
                        "text": f"\n\n--- {att.filename} ---\n{att.data}\n--- end {att.filename} ---",
                    })
                elif att.mime_type.startswith("image/"):
                    # Image file — send as image_url
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{att.mime_type};base64,{att.data}"},
                    })
                # PDFs and other binary formats: LiteLLM handles some via the
                # "file" content type, but support varies by provider. For v0.1,
                # we pass them as text descriptions and let the model ask for
                # more if needed. This can be extended per-provider later.
        history.append({"role": "user", "content": content_parts})
    else:
        history.append({"role": "user", "content": user_message})

    return history
