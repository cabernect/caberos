"""Shell/terminal built-in capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.terminal import close_terminal, read_terminal, shell_dialect_note, terminal_run


def register() -> None:
    registry.register(
        CapabilityDef(
            name="terminal",
            effects=frozenset(
                {"local_execute", "workspace_write", "external_write", "destructive"}
            ),
            kind="tool",
            description=(
                "Execute a shell command in the sandbox. By default, blocks until "
                "the command finishes and returns stdout/stderr. Set async=true to "
                "run the command in the background — returns a terminal_id you can "
                "poll with read_terminal and close with close_terminal." + shell_dialect_note()
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "The exact shell command to run, passed verbatim to "
                            "the shell — e.g. `ls -la`, `echo hello`. Do not "
                            "prefix with words like 'run' or 'execute'."
                        ),
                    },
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
            execute=terminal_run,
        )
    )

    registry.register(
        CapabilityDef(
            name="read_terminal",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Read incremental output from a background terminal. Pass the "
                "next_offset from the previous call to get only new output. "
                "wait_ms long-polls for output or completion (max 30000)."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "terminal_id": {
                        "type": "string",
                        "description": "Terminal session ID from terminal(async=true)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Byte offset for incremental stdout reads (next_offset from previous call)",
                        "default": 0,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max stdout chars to return (cap 65536)",
                        "default": 8192,
                    },
                    "wait_ms": {
                        "type": "integer",
                        "description": "Long-poll up to this many ms for new output or completion (cap 30000)",
                        "default": 0,
                    },
                },
                "required": ["terminal_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=read_terminal,
        )
    )

    registry.register(
        CapabilityDef(
            name="close_terminal",
            effects=frozenset({"local_execute"}),
            kind="tool",
            description="Close a background terminal session — terminates the process group if running and returns final output.",
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
            execute=close_terminal,
        )
    )
