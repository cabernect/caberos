"""Run-scoped capability discovery and schema loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config_schema import AgentConfig
from .registry import registry

DISCOVERY_CAPABILITY_NAMES = ("capabilities_search", "capabilities_load")
MCP_SERVER_GRANT_PREFIX = "mcp_server:"


def mcp_server_grant_name(server_id: str) -> str:
    """Return the stable agent-config grant name for an MCP server."""
    return f"{MCP_SERVER_GRANT_PREFIX}{server_id}"


def _server_id_for_capability(name: str) -> str | None:
    if not name.startswith("mcp."):
        return None
    from ..mcp import registry as mcp_registry

    mapping = mcp_registry._tool_map.get(name)
    return mapping[0] if mapping else None


def _grant_for(config: AgentConfig, name: str, server_id: str | None = None) -> Any:
    capability = registry.get(name)
    if capability is None:
        return None

    if config.capabilities is None:
        return capability if capability.kind != "mcp_tool" else None

    for grant in config.capabilities:
        if not grant.enabled:
            continue
        if grant.name == name:
            return grant
        if server_id and grant.name == mcp_server_grant_name(server_id):
            return grant
    return None


def is_capability_granted(
    config: AgentConfig,
    name: str,
    *,
    server_id: str | None = None,
) -> bool:
    """Check the configured authority ceiling for one registered capability."""
    return _grant_for(config, name, server_id) is not None


@dataclass
class CapabilityRunCatalog:
    """Permission-filtered capability metadata and run-scoped loaded schemas."""

    agent_config: AgentConfig
    db: Any = None
    run_id: str | None = None
    parent_config: AgentConfig | None = None
    max_results: int = 20
    max_load_per_call: int = 10
    max_loaded: int = 50
    loaded: set[str] = field(default_factory=set)

    def _is_permitted(self, name: str, server_id: str | None = None) -> bool:
        if not is_capability_granted(self.agent_config, name, server_id=server_id):
            return False
        if self.parent_config is not None and not is_capability_granted(
            self.parent_config, name, server_id=server_id
        ):
            return False
        return True

    async def _metadata(self) -> list[dict[str, Any]]:
        metadata: list[dict[str, Any]] = []
        for capability in registry.list_all():
            if capability.name in DISCOVERY_CAPABILITY_NAMES:
                continue
            server_id = _server_id_for_capability(capability.name)
            if not self._is_permitted(capability.name, server_id):
                continue
            grant = _grant_for(self.agent_config, capability.name, server_id)
            metadata.append(
                {
                    "name": capability.name,
                    "kind": capability.kind,
                    "description": capability.description,
                    "server_id": server_id,
                    "server_name": None,
                    "egress": capability.egress,
                    "require_approval": (
                        grant.require_approval
                        if grant is not None and hasattr(grant, "require_approval")
                        else capability.require_approval
                    ),
                    "always_loaded": bool(
                        grant is not None and getattr(grant, "always_loaded", False)
                    ),
                }
            )
        return metadata

    async def search(
        self,
        query: str = "",
        *,
        server: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return bounded metadata for capabilities inside the run's ceiling."""
        query_text = query.strip().lower()
        server_text = server.strip().lower() if server else None
        kind_text = kind.strip().lower() if kind else None
        limit = max(1, min(limit, self.max_results))

        results = []
        for item in await self._metadata():
            if query_text and query_text not in (f"{item['name']} {item['description']}".lower()):
                continue
            if kind_text and item["kind"].lower() != kind_text:
                continue
            if server_text and server_text not in (
                f"{item['server_id'] or ''} {item['server_name'] or ''}".lower()
            ):
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def can_discover(self) -> bool:
        """Return whether this agent has a non-empty capability ceiling."""
        if self.agent_config.capabilities is None:
            return True
        if not self.agent_config.capabilities:
            return False
        if self.parent_config is not None:
            if self.parent_config.capabilities is not None and not any(
                grant.enabled for grant in self.parent_config.capabilities
            ):
                return False
        return any(grant.enabled for grant in self.agent_config.capabilities)

    def _always_loaded(self, name: str, server_id: str | None = None) -> bool:
        capability = registry.get(name)
        if capability is None:
            return False
        grant = _grant_for(self.agent_config, name, server_id)
        if grant is None:
            return False
        if not hasattr(grant, "always_loaded"):
            return capability.kind != "mcp_tool"
        configured = getattr(grant, "always_loaded")
        if configured is None:
            return capability.kind != "mcp_tool"
        return bool(configured)

    def model_capability_names(self) -> list[str]:
        """Return capability names whose schemas are visible on the next turn."""
        if not self.can_discover():
            return []

        names: list[str] = []
        for capability in registry.list_all():
            server_id = _server_id_for_capability(capability.name)
            if capability.name in DISCOVERY_CAPABILITY_NAMES:
                names.append(capability.name)
            elif capability.name in self.loaded or self._always_loaded(capability.name, server_id):
                if self._is_permitted(capability.name, server_id):
                    names.append(capability.name)
        return names

    async def load(self, names: list[str]) -> dict[str, Any]:
        """Load permitted capability schemas for the next model turn."""
        metadata = {item["name"]: item for item in await self._metadata()}
        accepted: list[str] = []
        rejected: list[dict[str, str]] = []
        seen: set[str] = set()

        for name in names:
            if name in seen:
                continue
            seen.add(name)
            item = metadata.get(name)
            if item is None:
                rejected.append({"name": name, "reason": "Capability is not permitted"})
                continue
            if name in self.loaded:
                accepted.append(name)
                continue
            if len(self.loaded) >= self.max_loaded:
                rejected.append({"name": name, "reason": "Run capability limit reached"})
                continue
            if len(accepted) >= self.max_load_per_call:
                rejected.append({"name": name, "reason": "Load request limit reached"})
                continue
            self.loaded.add(name)
            accepted.append(name)

        return {
            "accepted": accepted,
            "rejected": rejected,
            "loaded": sorted(self.loaded),
        }
