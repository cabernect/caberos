"""Context assembly (D35 — order: base prompt, soul, persona, task, MEMORY.md, skills, KG, turns, recall).

The base system prompt (platform-level operating instructions) is always loaded
first, before the agent's identity. This tells the agent how to work inside
CaberOS regardless of its soul/persona/task.

The base prompt is adaptive: it only describes capabilities the agent actually
has enabled. If capabilities is empty, all built-in tools are enabled by default.
"""

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

from ..config_schema import AgentConfig
from ..models.run import Message
from .base_prompt import get_base_system_prompt


def _load_memory_md(agent_config: AgentConfig) -> str:
    """Load MEMORY.md from the agent home dir (D34). Returns empty string if missing."""
    from ..memory.notebook import read_memory

    return read_memory(agent_config.id)


def _load_skill_menu(agent_config: AgentConfig) -> str:
    """Load the skill menu (names + descriptions only) for the system prompt (D11b).

    Skills are NOT auto-injected — the agent sees a menu and calls skills_load
    to get the full content when it decides to use one.
    """
    from ..skills.loader import format_skill_menu

    return format_skill_menu(agent_config.id)


def get_enabled_capabilities(agent_config: AgentConfig) -> list[str]:
    """Return the list of enabled capability names for this agent.

    - capabilities is None (omitted in YAML) → all built-in tools enabled
      (tool, sub_agent, memory kinds). MCP tools are NOT included by default
      — they must be explicitly listed to avoid flooding the context window
      with potentially hundreds of MCP tool schemas.
    - capabilities is [] → no tools enabled
    - capabilities: [web_search, read_file, mcp.notion.notion-search] → only
      those tools enabled (including specific MCP tools)
    """
    from ..capabilities.registry import registry

    if agent_config.capabilities is None:
        # Default: all built-in tools, but NOT mcp_tool kind
        # MCP tools are opt-in to keep context size manageable
        caps = registry.list_all()
        return [cap.name for cap in caps if cap.kind != "mcp_tool"]

    return [grant.name for grant in agent_config.capabilities]


def assemble_system_prompt(
    agent_config: AgentConfig,
    user_message: str = "",
    kg_facts: list[dict[str, Any]] | None = None,
    recall_snippets: list[dict[str, Any]] | None = None,
    forced_skill: str | None = None,
    past_sessions: list[dict[str, Any]] | None = None,
    supports_vision: bool | None = None,
) -> str:
    """Build the system prompt from base prompt + agent identity (D35 order).

    Order:
    1. Base system prompt (platform instructions — adaptive to enabled tools)
    2. Soul (who the agent is — values, principles)
    3. Persona (how the agent communicates — tone, style)
    4. Task (what the agent does — mission, instructions)
    5. MEMORY.md (long-term memory — agent-curated notebook)
    6. Available Skills (menu — names + descriptions only)
    7. KG facts (knowledge graph — passed in by the harness from the DB)
    8. Past sessions (episodic — session summaries for topical recall)
    9. Recall snippets (semantic recall fallback — D34)
    10. Forced skill (slash command — full body injected when user types /skillname)
    11. Model capabilities (vision support — tells the agent if it can process images)
    """
    parts: list[str] = []

    # 1. Base system prompt — adaptive to enabled capabilities
    enabled_caps = get_enabled_capabilities(agent_config)
    parts.append(get_base_system_prompt(enabled_caps))

    # 2-4. Agent identity (D35)
    if agent_config.soul:
        parts.append(f"## Soul\n\n{agent_config.soul}")

    if agent_config.persona:
        parts.append(f"## Persona\n\n{agent_config.persona}")

    if agent_config.task:
        parts.append(f"## Task\n\n{agent_config.task}")

    # 5. MEMORY.md (D34 — agent-curated notebook, always loaded)
    memory_md = _load_memory_md(agent_config)
    if memory_md:
        parts.append(f"## MEMORY.md\n\n{memory_md}")

    # 6. Skills (D11b — menu only, not auto-injected)
    # The agent sees available skill names + descriptions, then calls
    # skills_load(name) to get the full content when it decides to use one.
    skill_menu = _load_skill_menu(agent_config)
    if skill_menu:
        parts.append(f"## Available Skills\n\n{skill_menu}")

    # 7. KG facts (D34 — knowledge graph triples for this contact)
    if kg_facts:
        facts_lines = [f"- ({f['subject']}, {f['predicate']}, {f['object']})" for f in kg_facts]
        parts.append("## Known Facts\n\n" + "\n".join(facts_lines))

    # 8. Past sessions (episodic — session summaries for topical recall)
    if past_sessions:
        # Char budget: ~500 chars total, truncate each summary
        budget = 500
        used = 0
        session_lines = []
        for s in past_sessions:
            summary = s.get("summary", "")
            if not summary:
                continue
            if used + len(summary) > budget:
                summary = summary[: budget - used] + "..."
            session_lines.append(f"- {summary}")
            used += len(summary)
            if used >= budget:
                break
        if session_lines:
            parts.append("## Past Context (recent sessions)\n\n" + "\n".join(session_lines))

    # 9. Recall snippets (D34 — semantic recall fallback, bounded)
    if recall_snippets:
        snippet_lines = [f"- [{s['key']}] {s['value']}" for s in recall_snippets]
        parts.append("## Relevant Past Context\n\n" + "\n".join(snippet_lines))

    # 10. Forced skill (slash command — /skillname message)
    # When the user types /skillname, the skill's full body is injected into
    # context so the agent has the instructions without calling skills_load.
    if forced_skill:
        from ..skills.loader import load_skill

        skill = load_skill(agent_config.id, forced_skill)
        if skill:
            parts.append(
                f"## Active Skill: {skill['name']}\n\n"
                f"{skill['body']}"
            )

    # 11. Model capabilities — tell the agent what its model can/can't do
    if supports_vision is not None:
        if supports_vision:
            parts.append(
                "## Model Capabilities\n\n"
                "Your model supports vision/image input. You can see and analyze "
                "images that the user attaches to their messages."
            )
        else:
            parts.append(
                "## Model Capabilities\n\n"
                "Your model does NOT support vision/image input. If the user "
                "attaches an image, you will receive it as text metadata only "
                "(filename, dimensions) — you cannot see the actual image content. "
                "Be honest about this limitation if asked. Do not claim you can "
                "see or analyze images."
            )

    return "\n\n---\n\n".join(parts)


def assemble_tool_schemas(agent_config: AgentConfig) -> list[dict[str, Any]]:
    """Build tool schemas from the agent's enabled capabilities.

    If capabilities is empty, all registered tools are included.
    """
    from ..capabilities.registry import registry

    enabled = get_enabled_capabilities(agent_config)
    schemas: list[dict[str, Any]] = []
    for name in enabled:
        cap = registry.get(name)
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
        # Skip thinking messages — they're internal, not a valid LLM role
        if msg.role == "thinking":
            continue
        # Convert tool_call messages to OpenAI format:
        #   assistant message with tool_calls + tool message with result
        if msg.role == "tool_call":
            try:
                tc = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                continue
            tool_name = tc.get("capability", "")
            call_id = tc.get("id", "")
            args = tc.get("args", {})
            result = tc.get("result", "")
            # Assistant message announcing the tool call
            history.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            )
            # Tool result message
            result_str = result if isinstance(result, str) else json.dumps(result)
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_str,
                }
            )
            continue
        # Skip empty assistant messages (e.g. failed runs, or placeholders after tool calls)
        if msg.role == "assistant" and not msg.content.strip():
            continue
        history.append({"role": msg.role, "content": msg.content})

    # Build the user message — multimodal if attachments are present
    if attachments:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        for att in attachments:
            if att.type == "image":
                # base64 data URI — model sees the image directly
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{att.mime_type};base64,{att.data}"},
                    }
                )
            elif att.type == "url":
                # URL — model fetches and processes it
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": att.data},
                    }
                )
            elif att.type == "file":
                # Text file — append content to the message text
                if att.mime_type.startswith("text/") or att.mime_type == "application/json":
                    content_parts.append(
                        {
                            "type": "text",
                            "text": f"\n\n--- {att.filename} ---\n{att.data}\n--- end {att.filename} ---",
                        }
                    )
                elif att.mime_type.startswith("image/"):
                    # Image file — send as image_url
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{att.mime_type};base64,{att.data}"},
                        }
                    )
                else:
                    # Binary file (PDF, docx, etc.) — already saved to workspace
                    # by the pipeline. The data field contains a path note.
                    # The file note is already in the message text, so we just
                    # add a brief reference here.
                    content_parts.append(
                        {
                            "type": "text",
                            "text": f"\n[Attachment: {att.filename} — {att.data}]",
                        }
                    )
        history.append({"role": "user", "content": content_parts})
    else:
        history.append({"role": "user", "content": user_message})

    return history
