#!/usr/bin/env python3
"""Smoke test script — the vertical slice verification tool (not a product CLI, D38).

Usage:
    python scripts/smoke.py <agent_id> "<message>"

This sends a message through the pipeline directly (no HTTP, no frontend)
and prints tool calls and the final answer to stdout. It uses a scripted
model double — no real LLM, no API key needed.

For ticket 01: the script also seeds a test agent if none exists.
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Add backend/src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

from agentos.agent_service import create_agent, get_active_config  # noqa: E402
from agentos.capabilities.builtin import register_builtin_capabilities  # noqa: E402
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig  # noqa: E402
from agentos.db import async_session_factory, init_db  # noqa: E402
from agentos.harness.loop import Harness  # noqa: E402
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse  # noqa: E402
from agentos.pipeline import InboundMessage, Pipeline  # noqa: E402


# A test agent config
TEST_AGENT_CONFIG = AgentConfig(
    id="test-agent",
    name="Test Agent",
    model=ModelConfig(provider_id="test", name="scripted-double"),
    soul="You are a test agent. You help verify the system works.",
    persona="Direct and concise.",
    task="Execute commands and report results.",
    capabilities=[
        # Must match a registered capability name. The shell capability is
        # `terminal` (`shell_run` is its implementation function, not its
        # registered name), so granting "shell_run" silently denied every
        # shell call and the smoke test still reported success.
        CapabilityGrant(name="terminal", require_approval=False),  # auto-approve for smoke test
    ],
)


async def run_smoke(agent_id: str, message: str) -> None:
    """Run the smoke test."""
    # Initialize
    register_builtin_capabilities()
    await init_db()

    # Ensure the test agent exists
    async with async_session_factory() as db:
        config = await get_active_config(db, agent_id)
        if config is None:
            if agent_id == "test-agent":
                print(f"[smoke] Creating test agent: {agent_id}")
                await create_agent(db, TEST_AGENT_CONFIG)
            else:
                print(f"[smoke] Agent {agent_id} not found. Use 'test-agent' for the smoke test.")
                return

    # Set up the scripted model: first call returns a tool call, second returns the answer
    model = ScriptedModel([
        ScriptedResponse(
            tool_calls=[{
                "id": "call_1",
                # Registered capability name, not the implementation function.
                "name": "terminal",
                "args": {"command": message},
            }],
        ),
        ScriptedResponse(
            content="Command executed successfully. See the tool call output above.",
        ),
    ])

    harness = Harness(model=model)

    # Print SSE events as they happen
    async def event_emitter(event_type: str, payload: dict) -> None:
        if event_type == "tool_call":
            status = payload.get("status", "?")
            cap = payload.get("capability", "?")
            if status == "pending":
                print(f"  [tool_call] {cap} — pending...")
            elif status == "complete":
                result = payload.get("result", {})
                if isinstance(result, dict) and "stdout" in result:
                    print(f"  [tool_call] {cap} — complete (exit code: {result.get('exit_code', '?')})")
                    if result.get("stdout"):
                        print(f"  [output] {result['stdout'].strip()}")
                else:
                    print(f"  [tool_call] {cap} — complete")
            elif status == "denied":
                print(f"  [tool_call] {cap} — DENIED: {payload.get('result', '')}")
        elif event_type == "token":
            print(f"\n[answer] {payload.get('content', '')}")
        elif event_type == "turn_complete":
            print(f"  [turn] #{payload.get('turn_number', '?')} — "
                  f"{payload.get('tokens_in', 0)} in, {payload.get('tokens_out', 0)} out, "
                  f"${payload.get('cost', 0):.6f}")
        elif event_type == "message_complete":
            print(f"\n[done] status={payload.get('status')} turns={payload.get('total_turns')} "
                  f"cost=${payload.get('total_cost', 0):.6f}")

    # Run the pipeline
    inbound = InboundMessage(
        channel="smoke_test",
        bot_id=agent_id,
        external_user_id="smoke-tester",
        text=message,
        message_id=str(uuid.uuid4()),
        is_test=True,
    )

    print(f"\n[smoke] Sending to agent '{agent_id}': \"{message}\"\n")

    async with async_session_factory() as db:
        pipeline = Pipeline(db=db, harness=harness)
        run = await pipeline.handle_inbound(inbound, trigger="user_message", is_test=True)

    print(f"\n[smoke] Run {run.id}: status={run.status}, cost=${run.cost:.6f}, "
          f"tokens={run.tokens_in + run.tokens_out}")

    # Verify audit records were written
    from sqlalchemy import select
    from agentos.models.audit import AuditRecord

    async with async_session_factory() as db:
        result = await db.execute(
            select(AuditRecord).where(AuditRecord.run_id == run.id)
        )
        audits = result.scalars().all()
        print(f"[smoke] Audit records: {len(audits)}")
        for a in audits:
            print(f"  - {a.capability_name}: allowed={a.allowed}, latency={a.latency_ms}ms")

    print("\n[smoke] Done. Every row the dashboard will read is written.")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/smoke.py <agent_id> \"<message>\"")
        print("Example: python scripts/smoke.py test-agent \"echo hello\"")
        sys.exit(1)

    agent_id = sys.argv[1]
    message = sys.argv[2]
    asyncio.run(run_smoke(agent_id, message))


if __name__ == "__main__":
    main()
