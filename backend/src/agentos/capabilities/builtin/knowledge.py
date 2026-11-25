"""Knowledge Vault document capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.knowledge import doc_inspect, doc_list, doc_query_rows, doc_search


def register() -> None:
    registry.register(
        CapabilityDef(
            name="doc_list",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "List documents available in the shared and active agent's private Knowledge Vault. "
                "Returns metadata only; use doc_search for excerpts and doc_inspect for visuals."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional filename or source-path filter",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "indexed", "failed"],
                        "description": "Optional document status filter",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum documents to return (default 20, maximum 50)",
                        "default": 20,
                    },
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=doc_list,
        )
    )

    registry.register(
        CapabilityDef(
            name="doc_search",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Search the Knowledge Vault for relevant document excerpts. Results combine "
                "shared knowledge with this agent's private knowledge and include source metadata. "
                "Use this before answering questions that may be covered by the operator's documents."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum excerpts to return (default 5, maximum 20)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=doc_search,
        )
    )

    registry.register(
        CapabilityDef(
            name="doc_inspect",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Inspect a page of a PDF or an embedded image in a DOCX using the model's "
                "vision capability. Use after doc_search identifies a relevant visual source."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID from doc_search"},
                    "page_number": {"type": "integer", "description": "PDF page number"},
                    "image_index": {
                        "type": "integer",
                        "description": "DOCX embedded image number",
                        "default": 1,
                    },
                },
                "required": ["document_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=doc_inspect,
        )
    )

    registry.register(
        CapabilityDef(
            name="doc_query_rows",
            effects=frozenset({"read"}),
            kind="tool",
            description=(
                "Query rows of a CSV/XLSX document in the Knowledge Vault exactly: "
                "allowlisted filters (eq, ne, lt, lte, gt, gte, contains), aggregates "
                "(count, sum, min, max) over the complete matching set, and paged rows "
                "with source coordinates. Use this for 'all rows where…', counts, or "
                "totals — doc_search only samples excerpts and cannot answer "
                "complete-set questions."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Document ID from doc_search/doc_list",
                    },
                    "sheet": {
                        "type": "string",
                        "description": "Sheet name (required when the document has several)",
                    },
                    "filters": {
                        "type": "array",
                        "description": "AND-combined predicates on columns (id or unique label)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {
                                    "type": "string",
                                    "enum": ["eq", "ne", "lt", "lte", "gt", "gte", "contains"],
                                },
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                    "aggregates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["count", "sum", "min", "max"]},
                                "column": {"type": "string"},
                            },
                            "required": ["op"],
                        },
                    },
                    "order": {"type": "string", "enum": ["asc", "desc"], "default": "asc"},
                    "limit": {"type": "integer", "default": 50, "maximum": 200},
                    "after_row": {
                        "type": "integer",
                        "description": "Continue after this source row (prior next_cursor)",
                        "default": 0,
                    },
                },
                "required": ["document_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=doc_query_rows,
        )
    )
