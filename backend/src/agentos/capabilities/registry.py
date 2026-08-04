"""Capability registry — source of truth for what capabilities exist (D9)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CapabilityDef:
    """Definition of a capability registered in the system."""

    name: str
    kind: Literal["tool", "memory", "mcp_tool"]
    description: str
    parameters_schema: dict[str, Any]
    egress: bool = False
    require_approval: bool = False
    subject_scoped: bool = False
    execute: Callable[..., Any] = field(default=lambda: None)


class CapabilityRegistry:
    """Registry of all available capabilities."""

    def __init__(self) -> None:
        self._caps: dict[str, CapabilityDef] = {}

    def register(self, cap: CapabilityDef) -> None:
        if cap.name in self._caps:
            return  # already registered — idempotent
        # D10: subject-scoped capabilities must not expose a subject parameter
        if cap.subject_scoped and "subject" in cap.parameters_schema.get("properties", {}):
            raise ValueError(
                f"Subject-scoped capability '{cap.name}' must not expose"
                " a 'subject' parameter (D10)"
            )
        self._caps[cap.name] = cap

    def get(self, name: str) -> CapabilityDef | None:
        return self._caps.get(name)

    def list_all(self) -> list[CapabilityDef]:
        return list(self._caps.values())

    def list_by_kind(self, kind: str) -> list[CapabilityDef]:
        return [c for c in self._caps.values() if c.kind == kind]

    def list_names(self) -> list[str]:
        return list(self._caps.keys())


# Global registry instance
registry = CapabilityRegistry()
