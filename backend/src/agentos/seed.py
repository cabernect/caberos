"""Seed script — creates default operator, capability registry, and default agents.

Default agent configs live as YAML files in `agentos/defaults/*.yaml`.
Capability definitions come from the runtime registry (capabilities/builtin.py),
so there's a single source of truth — no duplicated definitions here.

Run via: uv run python -m agentos.seed
"""

import json
from pathlib import Path

import bcrypt
import yaml
from sqlalchemy import select

from .db import async_session_factory, init_db
from .models.agent import Agent, AgentVersion
from .models.capability import Capability
from .models.operator import Operator

DEFAULTS_DIR = Path(__file__).parent / "defaults"


async def seed_operator_if_needed() -> None:
    """Create the default admin operator if none exists. Called on startup."""
    async with async_session_factory() as db:
        result = await db.execute(select(Operator).where(Operator.username == "admin"))
        if result.scalar_one_or_none() is None:
            password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            operator = Operator(
                username="admin", password_hash=password_hash, must_change_password=True
            )
            db.add(operator)
            await db.commit()
            print("Created default operator: admin/admin (change password on first login)")


async def seed_default_agents() -> None:
    """Create default agents from YAML files in agentos/defaults/ if they don't exist."""
    from .config_schema import AgentConfig

    async with async_session_factory() as db:
        for yaml_path in sorted(DEFAULTS_DIR.glob("*.yaml")):
            data = yaml.safe_load(yaml_path.read_text())
            agent_id = data.get("id", "")
            if not agent_id:
                continue

            # Skip if agent already exists
            result = await db.execute(select(Agent).where(Agent.id == agent_id))
            if result.scalar_one_or_none() is not None:
                continue

            config = AgentConfig.from_dict(data)
            config_json = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)

            agent = Agent(id=config.id, name=config.name, enabled=True)
            db.add(agent)
            await db.flush()

            version = AgentVersion(
                agent_id=config.id,
                version_number=1,
                config=config_json,
                is_active=True,
            )
            db.add(version)
            await db.flush()

            agent.active_version_id = version.id
            await db.flush()
            print(f"Created default agent: {config.id} ({config.name})")

        await db.commit()


async def seed() -> None:
    await init_db()

    # Register built-in capabilities in the runtime registry (single source of truth)
    from .capabilities.builtin import register_builtin_capabilities

    register_builtin_capabilities()

    async with async_session_factory() as db:
        # Seed default operator
        await seed_operator_if_needed()

        # Seed capabilities from the runtime registry (no duplication)
        from .capabilities.registry import registry

        for cap in registry.list_all():
            result = await db.execute(select(Capability).where(Capability.name == cap.name))
            if result.scalar_one_or_none() is None:
                db.add(
                    Capability(
                        name=cap.name,
                        kind=cap.kind,
                        description=cap.description,
                        parameters_schema=json.dumps(cap.parameters_schema),
                        egress=cap.egress,
                        require_approval=cap.require_approval,
                        subject_scoped=cap.subject_scoped,
                    )
                )
                print(f"Seeded capability: {cap.name}")

        await db.commit()

        # Seed default agents
        await seed_default_agents()

        print("Seed complete.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed())
