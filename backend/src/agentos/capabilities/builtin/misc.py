"""Interaction, utility, and sub-agent capabilities.

Registration order within this module matches the original
single-file builtin.py ordering.
"""

from ..registry import CapabilityDef, registry
from ..tools.datetime_tool import datetime_now
from ..tools.subagent import register_subagent_tools


def register() -> None:
    register_subagent_tools()

    # --- Interaction ---

    registry.register(
        CapabilityDef(
            name="agent_ask_user",
            effects=frozenset({"read"}),
            kind="tool",
            description="Ask the user a clarifying question and wait for their response. "
            "Use this when you need more information to proceed — e.g. 'which file?' "
            "or 'what format do you want?'. The run pauses until the user responds. "
            "Options can be simple strings or objects with label + description. "
            "Set multi_select=true to allow the user to pick multiple options.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user"},
                    "options": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label"],
                                },
                            ]
                        },
                        "description": "Optional list of choices. Each item can be a "
                        "string or {label, description}. If omitted, free-text input.",
                    },
                    "multi_select": {
                        "type": "boolean",
                        "description": "If true, the user can select multiple options. Default is false.",
                    },
                },
                "required": ["question"],
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=None,  # intercepted by mediator — never called directly
        )
    )

    # --- Utility ---

    registry.register(
        CapabilityDef(
            name="datetime_now",
            effects=frozenset({"read"}),
            kind="tool",
            description="Get the current date and time. Use this when you need to know "
            "what day it is, create timestamps, or reason about time.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone name (e.g. 'America/New_York'). Defaults to UTC.",
                    },
                },
            },
            egress=False,
            require_approval=False,
            subject_scoped=False,
            execute=datetime_now,
        )
    )
