"""Register built-in capabilities in the registry.

All capabilities are kind="tool". The old sub_agent kind is removed —
run_subagent is just another tool.
"""

from .registry import CapabilityDef, registry
from .tools.datetime_tool import datetime_now
from .tools.file import read_file, search_files, write_file
from .tools.knowledge import doc_search
from .tools.memory import (
    memory_query_facts,
    memory_recall,
    memory_remember_fact,
    memory_store,
    memory_update,
    search_history,
)
from .tools.shell import shell_run
from .tools.skills import skills_list, skills_load, skills_read_resource
from .tools.subagent import register_subagent_tools
from .tools.web import web_fetch, web_search


def register_builtin_capabilities() -> None:
    """Register all built-in capabilities. Called at startup."""

    # --- File ops ---

    registry.register(
        CapabilityDef(
            name="read_file",
            kind="tool",
            description="Read a full file or an inclusive line range from the agent's workspace",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the workspace"},
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read, 1-based and inclusive",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read, 1-based and inclusive",
                    },
                },
                "required": ["path"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=read_file,
        )
    )

    registry.register(
        CapabilityDef(
            name="write_file",
            kind="tool",
            description="Write a file to the agent's workspace",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the workspace"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=write_file,
        )
    )

    registry.register(
        CapabilityDef(
            name="search_files",
            kind="tool",
            description=(
                "Search files in the workspace. Three modes: "
                "'content' (grep-like content search, default), "
                "'name' (find files by glob pattern), "
                "'list' (list directory contents)."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["content", "name", "list"],
                        "description": "Search mode: 'content' (grep), 'name' (glob), 'list' (dir listing)",
                        "default": "content",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern. Required for 'content' (regex) and 'name' (glob) modes.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root)",
                        "default": ".",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File pattern filter for content mode (e.g. '*.py')",
                        "default": "*",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 50,
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case-insensitive search (content mode only)",
                        "default": False,
                    },
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=search_files,
        )
    )

    # --- Shell ops ---

    registry.register(
        CapabilityDef(
            name="terminal",
            kind="tool",
            description=(
                "Execute a shell command in the sandbox. By default, blocks until "
                "the command finishes and returns stdout/stderr. Set async=true to "
                "run the command in the background — returns a terminal_id you can "
                "poll with read_terminal and close with close_terminal."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "async": {
                        "type": "boolean",
                        "description": "If true, run in background and return terminal_id immediately",
                        "default": False,
                    },
                },
                "required": ["command"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=shell_run,
        )
    )

    registry.register(
        CapabilityDef(
            name="read_terminal",
            kind="tool",
            description="Read output from a background terminal session. Returns current stdout/stderr and whether the command is still running.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "terminal_id": {
                        "type": "string",
                        "description": "Terminal session ID from terminal(async=true)",
                    },
                },
                "required": ["terminal_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=None,  # handled by terminal registry
        )
    )

    registry.register(
        CapabilityDef(
            name="close_terminal",
            kind="tool",
            description="Close a background terminal session and return its final output.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "terminal_id": {
                        "type": "string",
                        "description": "Terminal session ID to close",
                    },
                },
                "required": ["terminal_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=None,  # handled by terminal registry
        )
    )

    # --- Knowledge Vault ---

    registry.register(
        CapabilityDef(
            name="doc_search",
            kind="tool",
            description=(
                "Search the Knowledge Vault for relevant document excerpts. Results combine "
                "shared knowledge with this agent's private knowledge and include source metadata. "
                "Use this before answering questions that may be covered by the operator's documents."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum excerpts to return (default 5, maximum 20)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=doc_search,
        )
    )

    # --- Web ops ---

    registry.register(
        CapabilityDef(
            name="web_search",
            kind="tool",
            description="Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
            "Use this to find current information, look up documentation, or research topics.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=web_search,
        )
    )

    registry.register(
        CapabilityDef(
            name="web_fetch",
            kind="tool",
            description="Fetch a URL and return its text content. For HTML pages, extracts "
            "readable text (removes scripts, styles, navigation). Use this to read web pages "
            "found via web_search.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=web_fetch,
        )
    )

    # --- Sub-agent ops ---

    register_subagent_tools()

    # --- Interaction ---

    registry.register(
        CapabilityDef(
            name="agent_ask_user",
            kind="tool",
            description="Ask the user a clarifying question and wait for their response. "
            "Use this when you need more information to proceed — e.g. 'which file?' "
            "or 'what format do you want?'. The run pauses until the user responds. "
            "Options can be simple strings or objects with label + description. "
            "Set multi_select=true to allow the user to pick multiple options.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user"},
                    "options": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label"],
                                },
                            ]
                        },
                        "description": "Optional list of choices. Each item can be a "
                        "string or {label, description}. If omitted, free-text input.",
                    },
                    "multi_select": {
                        "type": "boolean",
                        "description": "If true, the user can select multiple options. Default is false.",
                    },
                },
                "required": ["question"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=None,  # intercepted by mediator — never called directly
        )
    )

    # --- Utility ---

    registry.register(
        CapabilityDef(
            name="datetime_now",
            kind="tool",
            description="Get the current date and time. Use this when you need to know "
            "what day it is, create timestamps, or reason about time.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone name (e.g. 'America/New_York'). Defaults to UTC.",
                    },
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=datetime_now,
        )
    )

    # --- Memory (D34) ---

    registry.register(
        CapabilityDef(
            name="memory_recall",
            kind="memory",
            description=(
                "Recall past conversation snippets relevant to a query. "
                "Use this when you need to find something the user mentioned before "
                "that isn't in MEMORY.md or the knowledge graph."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_recall,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_store",
            kind="memory",
            description=(
                "Store a conversation snippet for later recall. Use this when the user "
                "shares something worth remembering but not important enough for MEMORY.md "
                "or a structured fact."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to store"},
                    "key": {
                        "type": "string",
                        "description": "Short label for the snippet",
                        "default": "snippet",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization",
                    },
                },
                "required": ["text"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_store,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_remember_fact",
            kind="memory",
            description=(
                "Store a structured fact as a (entity, predicate, object) triple in the "
                "knowledge graph. Use this for important, queryable facts about the user "
                "or their context — e.g. ('user', 'prefers', 'dark mode')."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "The entity the fact is about (e.g. 'user', 'project')",
                    },
                    "predicate": {
                        "type": "string",
                        "description": "The predicate (relation, e.g. 'prefers', 'works_on')",
                    },
                    "object": {
                        "type": "string",
                        "description": "The object (value, e.g. 'dark mode')",
                    },
                },
                "required": ["entity", "predicate", "object"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_remember_fact,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_query_facts",
            kind="memory",
            description=(
                "Query the knowledge graph for structured facts. All filters are optional "
                "and use exact match. Returns matching (entity, predicate, object) triples."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Filter by entity (the thing the fact is about)",
                    },
                    "predicate": {
                        "type": "string",
                        "description": "Filter by predicate (relation)",
                    },
                    "object": {"type": "string", "description": "Filter by object (value)"},
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_query_facts,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_update",
            kind="memory",
            description=(
                "Update MEMORY.md — the agent's long-term notebook. Use this when you learn "
                "something important about the user that should persist across all future "
                "sessions. The content replaces the entire file."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The new MEMORY.md content"},
                },
                "required": ["content"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,  # agent-scoped, not contact-scoped
            execute=memory_update,
        )
    )

    registry.register(
        CapabilityDef(
            name="search_history",
            kind="memory",
            description=(
                "Search raw message history for exact phrases or details. "
                "Use this when you need to find exactly what was said in a past "
                "conversation — error messages, config values, quotes, version numbers. "
                "This searches verbatim messages, not summaries."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in past messages",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=search_history,
        )
    )

    # --- Skills (D11b, D11c) ---
    # Skills are NOT auto-injected. The agent sees a menu in the system prompt
    # (names + descriptions), then calls skills_list or skills_load to get details.

    registry.register(
        CapabilityDef(
            name="skills_list",
            kind="tool",
            description=(
                "List all available skills (name + description only). "
                "Use this to discover what skills exist. Call skills_load(name) "
                "to get the full content of a specific skill."
            ),
            parameters_schema={"type": "object", "properties": {}},
            egress=False,
            require_approval=False,
            subject_scoped=False,
            silent=True,  # discovery only — don't show in chat as a tool call
            execute=skills_list,
        )
    )

    registry.register(
        CapabilityDef(
            name="skills_load",
            kind="tool",
            description=(
                "Load a specific skill's full content (SKILL.md body) and list its "
                "resources (templates, checklists, data files). Use this when you "
                "decide to apply a skill, or when the user asks you to use one. "
                "After loading, call skills_read_resource to read any resource files "
                "the skill body references."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The skill name (from skills_list)",
                    },
                },
                "required": ["name"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=skills_load,
        )
    )

    registry.register(
        CapabilityDef(
            name="skills_read_resource",
            kind="tool",
            description=(
                "Read a resource file from a skill directory (templates, checklists, "
                "data files). Use this after skills_load to read any resource the "
                "skill body references. The path is scoped to the skill directory — "
                "it cannot escape."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "The skill name (from skills_list)",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource filename (from skills_load resources listing)",
                    },
                },
                "required": ["skill", "resource"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=skills_read_resource,
        )
    )
