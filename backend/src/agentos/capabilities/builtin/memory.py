"""Memory and history-search capabilities (D34).

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.memory import (
    memory_query_facts,
    memory_recall,
    memory_remember_fact,
    memory_store,
    memory_update,
    search_history,
)


def register() -> None:
    registry.register(
        CapabilityDef(
            name="memory_recall",
            effects=frozenset({"read"}),
            kind="memory",
            description=(
                "Recall past conversation snippets relevant to a query. "
                "Use this when you need to find something the user mentioned before "
                "that isn't in MEMORY.md or the knowledge graph."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_recall,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_store",
            effects=frozenset({"workspace_write"}),
            kind="memory",
            description=(
                "Store a run-scoped working note for this task. Durable confirmed facts "
                "may be retained by post-run learning; this call alone does not guarantee "
                "persistence across sessions. Use memory_remember_fact for an explicit "
                "structured durable fact."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to store"},
                    "key": {
                        "type": "string",
                        "description": "Short label for the snippet",
                        "default": "snippet",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization",
                    },
                },
                "required": ["text"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_store,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_remember_fact",
            effects=frozenset({"workspace_write"}),
            kind="memory",
            description=(
                "Store a structured fact as a (entity, predicate, object) triple in the "
                "knowledge graph. Use this for important, queryable facts about the user "
                "or their context — e.g. ('user', 'prefers', 'dark mode')."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "The entity the fact is about (e.g. 'user', 'project')",
                    },
                    "predicate": {
                        "type": "string",
                        "description": "The predicate (relation, e.g. 'prefers', 'works_on')",
                    },
                    "object": {
                        "type": "string",
                        "description": "The object (value, e.g. 'dark mode')",
                    },
                },
                "required": ["entity", "predicate", "object"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_remember_fact,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_query_facts",
            effects=frozenset({"read"}),
            kind="memory",
            description=(
                "Query the knowledge graph for structured facts. All filters are optional "
                "and use exact match. Returns matching (entity, predicate, object) triples."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Filter by entity (the thing the fact is about)",
                    },
                    "predicate": {
                        "type": "string",
                        "description": "Filter by predicate (relation)",
                    },
                    "object": {"type": "string", "description": "Filter by object (value)"},
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=memory_query_facts,
        )
    )

    registry.register(
        CapabilityDef(
            name="memory_update",
            effects=frozenset({"workspace_write"}),
            kind="memory",
            description=(
                "Update the curated memory portion of the bounded always-loaded MEMORY.md "
                "core. Include only clear durable general preferences and a few standing "
                "facts, not detailed project history. Managed soul/persona/task is read-only. "
                "Core updates apply to future sessions; this session keeps its pinned core."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The new MEMORY.md content"},
                    "expected_hash": {
                        "type": "string",
                        "description": "Whole-file hash your edit is based on — returned on conflict for a safe retry.",
                    },
                },
                "required": ["content"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,  # agent-scoped, not contact-scoped
            execute=memory_update,
        )
    )

    registry.register(
        CapabilityDef(
            name="search_history",
            effects=frozenset({"read"}),
            kind="memory",
            description=(
                "Search raw message history for exact phrases or details. "
                "Use this when you need to find exactly what was said in a past "
                "conversation — error messages, config values, quotes, version numbers. "
                "This searches verbatim messages, not summaries. During session-close "
                "reflection, reads are confined to frozen session evidence; an empty "
                "query pages that evidence, and run/message selectors and content "
                "offsets allow targeted original reads."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in past messages",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 5)",
                        "default": 5,
                    },
                    "run_id": {"type": "string"},
                    "message_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "content_offset": {"type": "integer", "minimum": 0},
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=True,
            execute=search_history,
        )
    )
