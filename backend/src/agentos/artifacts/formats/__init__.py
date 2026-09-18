"""Format handlers — pure bytes-in/bytes-out Office ops.

Handlers never touch the DB or the filesystem outside explicitly provided
paths; the artifact service owns revisions, containment, and provenance.
"""

from . import docx

_HANDLERS = {"docx": docx, "docm": docx}


class UnsupportedFormatError(Exception):
    pass


def get_handler(fmt: str):
    handler = _HANDLERS.get(fmt)
    if handler is None:
        raise UnsupportedFormatError(f"no structured handler for format: {fmt}")
    return handler
