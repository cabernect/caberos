"""Register built-in capabilities in the registry.

All capabilities are kind="tool". The old sub_agent kind is removed —
run_subagent is just another tool.

Registration is split per domain under this package; the call order in
``register_builtin_capabilities`` preserves the original single-file
ordering exactly, since catalog order is observable.
"""

from . import (
    artifacts,
    browser,
    files,
    knowledge,
    media,
    memory,
    misc,
    shell,
    skills,
    web,
)


def register_builtin_capabilities() -> None:
    """Register all built-in capabilities. Called at startup."""
    files.register()
    shell.register()
    knowledge.register()
    web.register()
    browser.register()
    misc.register()
    memory.register()
    skills.register()
    artifacts.register()
    media.register()
