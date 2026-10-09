"""Outcome → tool-event status mapping, shared by harness SSE and the
observability timeline so both surfaces name a call's end the same way.

Policy outcomes (denied) and runtime outcomes (error/timeout/interrupted)
stay distinct; anything unrecognised fails closed.
"""

_OUTCOME_TO_STATUS = {
    "ok": "complete",
    "denied": "denied",
    "error": "failed",
    "timeout": "timeout",
    "interrupted": "interrupted",
}


def tool_event_status(outcome: str | None) -> str:
    """Map an audit/SyscallResult outcome to the tool_event status vocabulary."""
    return _OUTCOME_TO_STATUS.get(outcome or "", "failed")
