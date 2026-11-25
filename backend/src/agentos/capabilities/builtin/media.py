"""Image generation/editing capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.media import image_edit, image_generate


def register() -> None:
    registry.register(
        CapabilityDef(
            name="image_generate",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description="Generate one image from a text prompt and save it as a "
            "tracked workspace artifact. To edit an existing workspace image, "
            "use image_edit instead. Requires a configured image binding "
            "(Settings → Tools) — provider, model, size and quality are "
            "operator-set, not call arguments.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Image prompt (max 4000 chars)",
                    },
                },
                "required": ["prompt"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=image_generate,
        )
    )

    registry.register(
        CapabilityDef(
            name="image_edit",
            effects=frozenset({"workspace_write"}),
            kind="tool",
            description="Edit a workspace image (e.g. an attachment or prior "
            "artifact) following an instruction, and save the result as a "
            "tracked workspace artifact. For fresh generation without a source "
            "image, use image_generate instead. Requires a configured image "
            "binding (Settings → Tools).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Edit instruction (max 4000 chars)",
                    },
                    "source_image": {
                        "type": "string",
                        "description": "Workspace-relative path to the image to edit",
                    },
                },
                "required": ["prompt", "source_image"],
            },
            egress=True,
            require_approval=True,
            subject_scoped=False,
            execute=image_edit,
        )
    )
