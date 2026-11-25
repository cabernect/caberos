"""Artifact Studio capabilities (W2).

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.artifact import (
    artifact_adopt,
    artifact_create,
    artifact_history,
    artifact_inspect,
    artifact_restore,
    artifact_revise,
)


def register() -> None:
    _doc_spec_hint = (
        "Structured document spec — e.g. docx: {title?, blocks:[heading|"
        "paragraph|list|table|image|page_break]}; xlsx: {sheets:[{name,rows,"
        "cells,freeze,column_widths,formats}]}; pptx: {slides:[{layout,title,"
        "subtitle,blocks:[bullets|table|image|chart|notes|text]}]}; deck "
        "(.deck.json, the editable presentation source shared by the HTML "
        'player and PPTX export): {kind:"deck", title?, theme?{background,'
        "accent,text,font:sans|serif|mono}, slides:[{id?,layout?:title|content|"
        "two_content|section,title?,blocks?[heading|paragraph|bullets|table|"
        "image|divider],notes?,transition?}], motion?{transition:{type:none|fade|slide,"
        "duration_ms:0..2000},entrance:{type:none|fade|rise,duration_ms:0..2000}}}. "
        "Blocks may set id, reveal:true or reveal:'items' (bullets only), "
        "animation:{type:none|fade|rise,duration_ms:0..2000}. Motion plays in "
        "Slideshow; PPTX shows final static content. image blocks take "
        "src=workspace-relative raster paths (png/jpg/gif/webp, pinned as "
        "embedded snapshots at build; no scripts/external URLs)."
    )
    registry.register(
        CapabilityDef(
            name="artifact_create",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description=(
                "Create a versioned deliverable (docx/xlsx/pptx/deck) in the "
                "workspace from a structured spec — never raw file bytes. Files "
                "are saved under artifacts/ (prefix added automatically). " + _doc_spec_hint
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Output path relative to artifacts/ (e.g. report.docx → artifacts/report.docx)",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["docx", "xlsx", "pptx", "deck"],
                        "description": "Format; inferred from path extension when omitted",
                    },
                    "spec": {"type": "object", "description": _doc_spec_hint},
                    "change_summary": {
                        "type": "string",
                        "description": "Short note recorded on revision 1",
                    },
                },
                "required": ["path", "spec"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_create,
        )
    )

    registry.register(
        CapabilityDef(
            name="artifact_inspect",
            effects=frozenset({"read"}),
            kind="tool",
            description="Inspect a tracked artifact — validity, structure (headings/sheets/slides), tracking status.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                },
                "required": ["artifact_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_inspect,
        )
    )

    registry.register(
        CapabilityDef(
            name="artifact_revise",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description=(
                "Apply structured edit ops to an artifact → new immutable revision. "
                "Requires base_revision_id (from inspect/history); conflicts instead "
                "of overwriting when the file changed externally. Ops — docx: "
                "append_blocks|replace_paragraph|set_cell; xlsx: set_cell|append_rows|"
                "add_sheet|remove_sheet; pptx: add_slide|move_slide|set_title|append_bullets; "
                "deck (.deck.json): set_title|set_theme|add_slide|remove_slide|set_slide|"
                "move_slide (slide refs are 0-based index or slide id)."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "base_revision_id": {
                        "type": "string",
                        "description": "Revision the edit is based on — get it from artifact_inspect",
                    },
                    "ops": {"type": "array", "items": {"type": "object"}},
                    "change_summary": {"type": "string"},
                },
                "required": ["artifact_id", "base_revision_id", "ops"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_revise,
        )
    )

    registry.register(
        CapabilityDef(
            name="artifact_adopt",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description="Start tracking an existing workspace file (download, import, user drop) — current bytes become revision 1.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"},
                    "change_summary": {"type": "string"},
                },
                "required": ["path"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_adopt,
        )
    )

    registry.register(
        CapabilityDef(
            name="artifact_history",
            effects=frozenset({"read"}),
            kind="tool",
            description="List an artifact's revisions, newest first — revision ids, summaries, provenance.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                },
                "required": ["artifact_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_history,
        )
    )

    registry.register(
        CapabilityDef(
            name="artifact_restore",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description="Write an old revision's bytes back to the workspace as a NEW revision — history is never rewritten. Deck restores also require the current base_revision_id; stale restores fail.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "revision_id": {"type": "string"},
                    "base_revision_id": {
                        "type": "string",
                        "description": "Current revision id; required when restoring a deck.",
                    },
                    "change_summary": {"type": "string"},
                },
                "required": ["artifact_id", "revision_id"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=artifact_restore,
        )
    )
