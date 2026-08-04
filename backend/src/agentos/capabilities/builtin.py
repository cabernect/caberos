"""Register built-in capabilities in the registry.

All capabilities are kind="tool". The old sub_agent kind is removed —
run_subagent is just another tool.
"""

from .registry import CapabilityDef, registry
from .tools.datetime_tool import datetime_now
from .tools.file import read_file, search_files, write_file
from .tools.shell import shell_run
from .tools.subagent import register_subagent_tools
from .tools.web import web_fetch, web_search


def register_builtin_capabilities() -> None:
    """Register all built-in capabilities. Called at startup."""

    # --- File ops ---

    registry.register(
        CapabilityDef(
            name="read_file",
            kind="tool",
            description="Read a file from the agent's workspace",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the workspace"}
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
