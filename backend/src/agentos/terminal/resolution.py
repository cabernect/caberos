"""Resolve which sandbox backend a strict-mode shell uses (W11.2).

The exec.terminal binding supplies defaults, never a gate: no row or an
"auto" pick resolves to the OS-native backend exactly as before. An explicit
pick must be supported and installed — a bad choice returns an
UnavailableBackend that refuses honestly, with the binding's reason, instead
of falling back to Auto or another backend.
"""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..capabilities.bindings import resolve_binding
from ..sandbox import get_backend
from ..sandbox.base import SandboxBackend, UnavailableBackend, backend_named


async def resolve_terminal_backend(
    db: AsyncSession, *, native: Callable[[], SandboxBackend] = get_backend
) -> tuple[SandboxBackend, int | None]:
    """The backend strict-mode terminal calls use, plus the binding revision
    for the admission pin (None when no binding row exists).

    `native` supplies Auto resolution — callers pass their own reference so
    tests can patch the auto path at the call site (registry.get_backend).
    """
    resolution = await resolve_binding(db, "exec.terminal")
    revision = resolution.binding.revision if resolution.binding else None
    if resolution.state == "invalid":
        return (
            UnavailableBackend(reason=f"Terminal backend binding is invalid: {resolution.reason}"),
            revision,
        )
    selected = resolution.options.get("backend") or "auto"
    if selected == "auto":
        return native(), revision
    return backend_named(selected), revision
