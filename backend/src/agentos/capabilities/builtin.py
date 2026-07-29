"""Register built-in capabilities in the registry."""

from .registry import CapabilityDef, registry
from .tools.file import file_list, file_read, file_write
from .tools.shell import shell_run


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
