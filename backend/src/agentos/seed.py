"""Seed script — creates default operator and capability registry.

Run via: uv run python -m agentos.seed
"""

import json

import bcrypt
from sqlalchemy import select

from .db import async_session_factory, init_db
from .models.capability import Capability
from .models.operator import Operator

# Built-in capabilities (D9 — four kinds in v0.1: tool, sub_agent, memory, connector_action)
BUILTIN_CAPABILITIES = [
    {
        "name": "file.read",
        "kind": "tool",
        "description": "Read a file from the agent's workspace",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the workspace"}
            },
            "required": ["path"],
        },
        "egress": False,
        "require_approval": False,
        "subject_scoped": False,
    },
    {
        "name": "file.write",
        "kind": "tool",
        "description": "Write a file to the agent's workspace",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the workspace"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        "egress": False,
        "require_approval": False,
        "subject_scoped": False,
    },
    {
        "name": "file.list",
        "kind": "tool",
        "description": "List files in a directory within the workspace",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative directory path", "default": "."}
            },
        },
        "egress": False,
        "require_approval": False,
        "subject_scoped": False,
    },
    {
        "name": "shell.run",
        "kind": "tool",
        "description": "Execute a shell command in the sandbox",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"}
            },
            "required": ["command"],
        },
        "egress": True,
        "require_approval": True,  # default true for safety; can be overridden per-agent
        "subject_scoped": False,
    },
    {
        "name": "memory.recall",
        "kind": "memory",
        "description": "Recall relevant memories for the current user",
        "parameters_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to recall"}},
            "required": ["query"],
        },
        "egress": False,
        "require_approval": False,
        "subject_scoped": True,  # subject injected by syscall layer (D10)
    },
    {
        "name": "memory.store",
        "kind": "memory",
        "description": "Store a memory for the current user",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key"},
                "value": {"type": "string", "description": "Memory value"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags",
                },
            },
            "required": ["key", "value"],
        },
        "egress": False,
        "require_approval": False,
        "subject_scoped": True,
    },
]


async def seed() -> None:
    await init_db()

    async with async_session_factory() as db:
        # Seed default operator
        result = await db.execute(select(Operator).where(Operator.username == "admin"))
        if result.scalar_one_or_none() is None:
            password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            operator = Operator(
                username="admin", password_hash=password_hash, must_change_password=True
            )
            db.add(operator)
            print("Created default operator: admin/admin (change password on first login)")

        # Seed capabilities
        for cap_data in BUILTIN_CAPABILITIES:
            result = await db.execute(select(Capability).where(Capability.name == cap_data["name"]))
            if result.scalar_one_or_none() is None:
                cap = Capability(
                    name=cap_data["name"],
                    kind=cap_data["kind"],
                    description=cap_data["description"],
                    parameters_schema=json.dumps(cap_data["parameters_schema"]),
                    egress=cap_data["egress"],
                    require_approval=cap_data["require_approval"],
                    subject_scoped=cap_data["subject_scoped"],
                )
                db.add(cap)
                print(f"Seeded capability: {cap_data['name']}")

        await db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed())
