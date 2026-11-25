"""Governed skill-library and capability-catalog capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.catalog import capabilities_load, capabilities_search
from ..tools.skills import skills_list, skills_load, skills_read_resource, skills_usage


def register() -> None:
    # Skills are NOT auto-injected. The agent sees a menu in the system prompt
    # (names + descriptions), then calls skills_list or skills_load to get details.

    registry.register(
        CapabilityDef(
            name="skills_list",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "List all available skills (name + description only). "
                "Use this to discover what skills exist. Call skills_load(name) "
                "to get the full content of a specific skill."
            ),
            parameters_schema={"type": "object", "properties": {}},
            egress=False,
            require_approval=False,
            subject_scoped=False,
            silent=True,  # discovery only — don't show in chat as a tool call
            execute=skills_list,
        )
    )

    registry.register(
        CapabilityDef(
            name="skills_load",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Load a specific skill's full content (SKILL.md body) and list its "
                "resources (templates, checklists, data files). Use this when you "
                "decide to apply a skill, or when the user asks you to use one. "
                "After loading, call skills_read_resource to read any resource files "
                "the skill body references."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The skill name (from skills_list)",
                    },
                },
                "required": ["name"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=skills_load,
        )
    )

    registry.register(
        CapabilityDef(
            name="skills_read_resource",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Read a resource file from a skill directory (templates, checklists, "
                "data files). Use this after skills_load to read any resource the "
                "skill body references. The path is scoped to the skill directory — "
                "it cannot escape. Text reads support character offsets for paging."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "The skill name (from skills_list)",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource filename (from skills_load resources listing)",
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "required": ["skill", "resource"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=skills_read_resource,
        )
    )

    registry.register(
        CapabilityDef(
            name="skills_usage",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Inspect recorded activations of a visible skill in your own "
                "conversation scope to inform revision; counts do not prove effectiveness."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The skill name (from skills_list)",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=skills_usage,
        )
    )

    registry.register(
        CapabilityDef(
            name="capabilities_search",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Search the capabilities permitted for this run by name, server name, "
                "or description — covers built-in tools, memory tools, and MCP server "
                "tools alike. Returns compact metadata only; use capabilities_load to "
                "make selected tool schemas available for the next model turn."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to match against capability names, server names, and descriptions",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 20, maximum 50)",
                        "default": 20,
                    },
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=capabilities_search,
        )
    )

    registry.register(
        CapabilityDef(
            name="capabilities_load",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Load selected permitted capability schemas for the next model turn. "
                "Use exact names returned by capabilities_search. Loading never grants "
                "new authority."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact capability names to load",
                    }
                },
                "required": ["names"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=capabilities_load,
        )
    )
