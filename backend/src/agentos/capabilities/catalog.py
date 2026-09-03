"""Run-scoped capability discovery and schema loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from ..config_schema import AgentConfig
from ..models.mcp import McpServer, McpTool
from .registry import CapabilityDef, registry

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


def has_discovery_access(config: AgentConfig) -> bool:
    """Return whether an agent has any enabled authority to discover tools."""
    if config.capabilities is None:
        return True
    return any(grant.enabled for grant in config.capabilities)


def _grant_for(config: AgentConfig, name: str, server_id: str | None = None) -> Any:
    capability = registry.get(name)
    if capability is None:
        return None

    if name in DISCOVERY_CAPABILITY_NAMES:
        return capability if has_discovery_access(config) else None

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
    _metadata_cache: list[dict[str, Any]] | None = field(default=None, init=False, repr=False)

    def _is_permitted(self, name: str, server_id: str | None = None) -> bool:
        if not is_capability_granted(self.agent_config, name, server_id=server_id):
            return False
        if self.parent_config is not None and not is_capability_granted(
            self.parent_config, name, server_id=server_id
        ):
            return False
        return True

    async def _metadata(self) -> list[dict[str, Any]]:
        if self._metadata_cache is not None:
            return self._metadata_cache

        metadata_by_name: dict[str, dict[str, Any]] = {}
        for capability in registry.list_all():
            if capability.name in DISCOVERY_CAPABILITY_NAMES or capability.kind == "mcp_tool":
                continue
            if not self._is_permitted(capability.name):
                continue
            grant = _grant_for(self.agent_config, capability.name)
            metadata_by_name[capability.name] = {
                "name": capability.name,
                "kind": capability.kind,
                "description": capability.description,
                "server_id": None,
                "server_name": None,
                "egress": capability.egress,
                "require_approval": (
                    grant.require_approval
                    if grant is not None and hasattr(grant, "require_approval")
                    else capability.require_approval
                ),
                "always_loaded": self._always_loaded(capability.name),
            }

        if self.db is not None:
            result = await self.db.execute(
                select(McpTool, McpServer)
                .join(McpServer, McpServer.id == McpTool.mcp_server_id)
                .where(McpServer.enabled.is_(True))
            )
            for tool, server in result.all():
                capability = registry.get(tool.capability_name)
                if capability is None:
                    capability = CapabilityDef(
                        name=tool.capability_name,
                        kind="mcp_tool",
                        description=tool.description,
                        parameters_schema=json.loads(tool.parameters_schema),
                        egress=tool.egress,
                        require_approval=tool.require_approval,
                        subject_scoped=tool.subject_scoped,
                    )
                    registry.register(capability)
                from ..mcp import registry as mcp_registry

                mcp_registry._tool_map[tool.capability_name] = (server.id, tool.tool_name)
                if not self._is_permitted(tool.capability_name, server.id):
                    continue
                grant = _grant_for(self.agent_config, tool.capability_name, server.id)
                metadata_by_name[tool.capability_name] = {
                    "name": tool.capability_name,
                    "kind": "mcp_tool",
                    "description": tool.description,
                    "server_id": server.id,
                    "server_name": server.name,
                    "egress": tool.egress,
                    "require_approval": (
                        grant.require_approval if grant is not None else tool.require_approval
                    ),
                    "always_loaded": self._always_loaded(tool.capability_name, server.id),
                }
        else:
            for capability in registry.list_by_kind("mcp_tool"):
                server_id = _server_id_for_capability(capability.name)
                if not self._is_permitted(capability.name, server_id):
                    continue
                grant = _grant_for(self.agent_config, capability.name, server_id)
                metadata_by_name[capability.name] = {
                    "name": capability.name,
                    "kind": capability.kind,
                    "description": capability.description,
                    "server_id": server_id,
                    "server_name": None,
                    "egress": capability.egress,
                    "require_approval": grant.require_approval
                    if grant is not None
                    else capability.require_approval,
                    "always_loaded": self._always_loaded(capability.name, server_id),
                }

        self._metadata_cache = list(metadata_by_name.values())
        return self._metadata_cache

    async def prepare(self) -> None:
        """Load the permission-filtered catalog before the first model turn."""
        await self._metadata()

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
            searchable = f"{item['name']} {item['description']}".lower()
            if query_text and not all(token in searchable for token in query_text.split()):
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
