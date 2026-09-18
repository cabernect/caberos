"""Format handlers — pure bytes-in/bytes-out Office ops.

Handlers never touch the DB or the filesystem outside explicitly provided
paths; the artifact service owns revisions, containment, and provenance.
"""

from . import docx, xlsx

# Macro-enabled formats (docm/xlsm/pptm) intentionally have no handler —
# the plan keeps them read-only/unsupported rather than risk macro loss.
_HANDLERS = {"docx": docx, "xlsx": xlsx}


class UnsupportedFormatError(Exception):
    pass


def get_handler(fmt: str):
    handler = _HANDLERS.get(fmt)
    if handler is None:
        raise UnsupportedFormatError(f"no structured handler for format: {fmt}")
    return handler
