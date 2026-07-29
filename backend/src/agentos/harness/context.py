"""Context assembly (D35 — order: soul, persona, task, MEMORY.md, skills, KG, turns, recall).

For ticket 01 (smoke test), this loads soul/persona/task from AgentConfig.
MEMORY.md, skills, KG facts, and semantic recall come in ticket 06.
"""

from typing import Any

from ..config_schema import AgentConfig
from ..models.run import Message


def assemble_system_prompt(agent_config: AgentConfig) -> str:
    """Build the system prompt from agent identity (D35 order)."""
    parts: list[str] = []

    if agent_config.soul:
        parts.append(f"## Soul\n\n{agent_config.soul}")

    if agent_config.persona:
        parts.append(f"## Persona\n\n{agent_config.persona}")

    if agent_config.task:
        parts.append(f"## Task\n\n{agent_config.task}")

    # MEMORY.md loading will be added in ticket 06
    # Skills loading will be added in ticket 06
    # KG facts will be added in ticket 06

    return "\n\n".join(parts) if parts else "You are a helpful assistant."


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
) -> list[dict[str, str]]:
    """Build the message history for the model call."""
    history: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    for msg in recent_messages:
        history.append({"role": msg.role, "content": msg.content})

    history.append({"role": "user", "content": user_message})
    return history
