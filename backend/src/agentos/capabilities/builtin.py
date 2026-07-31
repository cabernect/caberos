"""Register built-in capabilities in the registry."""

from .registry import CapabilityDef, registry
from .tools.datetime_tool import datetime_now
from .tools.file import file_list, file_read, file_write
from .tools.search import file_glob, file_search
from .tools.shell import shell_run
from .tools.web import web_fetch, web_search


def register_builtin_capabilities() -> None:
    """Register all built-in capabilities. Called at startup."""
    registry.register(
        CapabilityDef(
            name="file.read",
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
            execute=file_read,
        )
    )

    registry.register(
        CapabilityDef(
            name="file.write",
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
            execute=file_write,
        )
    )

    registry.register(
        CapabilityDef(
            name="file.list",
            kind="tool",
            description="List files in a directory within the workspace",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path",
                        "default": ".",
                    }
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=file_list,
        )
    )

    registry.register(
        CapabilityDef(
            name="shell.run",
            kind="tool",
            description="Execute a shell command in the sandbox",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=shell_run,
        )
    )

    # agent.ask_user — elicitation capability (human-in-the-loop)
    # This capability is intercepted by the mediator (no normal execute function).
    # When the agent calls it, the run pauses and the user is asked to provide input.
    registry.register(
        CapabilityDef(
            name="agent.ask_user",
            kind="tool",
            description="Ask the user a clarifying question and wait for their response. "
            "Use this when you need more information to proceed — e.g. 'which file?' "
            "or 'what format do you want?'. The run pauses until the user responds. "
            "Options can be simple strings or objects with label + description. "
            "Set multi_select=true to allow the user to pick multiple options.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
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
                        "description": "If true, the user can select multiple options. "
                        "Default is false (single select).",
                    },
                },
                "required": ["question"],
            },
            egress=False,
            require_approval=False,  # asking a question is never dangerous
            subject_scoped=False,
            execute=None,  # intercepted by mediator — never called directly
        )
    )

    # file.search — grep within workspace files
    registry.register(
        CapabilityDef(
            name="file.search",
            kind="tool",
            description="Search file contents within the workspace (like grep). "
            "Returns matching lines with file paths and line numbers.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression or literal string to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root)",
                        "default": ".",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File pattern filter (e.g. '*.py')",
                        "default": "*",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return",
                        "default": 50,
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case-insensitive search",
                        "default": False,
                    },
                },
                "required": ["pattern"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=file_search,
        )
    )

    # file.glob — find files by name pattern
    registry.register(
        CapabilityDef(
            name="file.glob",
            kind="tool",
            description="Find files by name pattern within the workspace (like find/glob). "
            "Returns relative file paths.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. '*.py', '**/test_*.py')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root)",
                        "default": ".",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum files to return",
                        "default": 100,
                    },
                },
                "required": ["pattern"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=file_glob,
        )
    )

    # datetime.now — current date and time
    registry.register(
        CapabilityDef(
            name="datetime.now",
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

    # web.search — search the web (DuckDuckGo, free, no API key)
    registry.register(
        CapabilityDef(
            name="web.search",
            kind="tool",
            description="Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
            "Use this to find current information, look up documentation, or research topics.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=True,
            require_approval=True,  # network access — require approval
            subject_scoped=False,
            execute=web_search,
        )
    )

    # web.fetch — fetch a URL and return text content
    registry.register(
        CapabilityDef(
            name="web.fetch",
            kind="tool",
            description="Fetch a URL and return its text content. For HTML pages, extracts "
            "readable text (removes scripts, styles, navigation). Use this to read web pages "
            "found via web.search.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
            egress=True,
            require_approval=True,  # network access — require approval
            subject_scoped=False,
            execute=web_fetch,
        )
    )
