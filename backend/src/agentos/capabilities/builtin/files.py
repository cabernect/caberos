"""File-operation built-in capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.file import edit_file, read_file, search_files, write_file


def register() -> None:
    registry.register(
        CapabilityDef(
            name="read_file",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Read a file from the agent's workspace. Text files support an "
                "inclusive line range; PDFs extract text per page (start_page/"
                "end_page); DOCX/PPTX/XLSX return extracted text; images return "
                "image content on vision-capable models. Output is capped at "
                "50k chars — page through large files."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the workspace"},
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read, 1-based and inclusive (text files)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read, 1-based and inclusive (text files)",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "First PDF page to extract, 1-based and inclusive",
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "Last PDF page to extract, 1-based and inclusive",
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
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description=(
                "Write a UTF-8 file — creates new files or replaces an existing "
                "file's whole content. For a small change to an existing text "
                "file, prefer edit_file so only the changed fragment is sent."
            ),
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
            name="edit_file",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description=(
                "Edit an existing UTF-8 text file by replacing one exact, unique "
                "old_text fragment with new_text. Refuses missing or ambiguous "
                "matches without changing the file. Cannot create files or edit "
                "binary/Office/PDF content — read the current text first."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Existing file path"},
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to replace; include enough context to be unique",
                    },
                    "new_text": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=edit_file,
        )
    )

    registry.register(
        CapabilityDef(
            name="search_files",
            effects=frozenset({"read"}),
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
