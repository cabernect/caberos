import asyncio
import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentos import db as db_module
from agentos.agent_service import create_agent
from agentos.config import settings
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.db_backends.sqlite_backend import SQLiteBackend
from agentos.harness.loop import Harness
from agentos.harness.scripted_model import ScriptedModel, ScriptedResponse
from agentos.models.approval import ApprovalRequest
from agentos.models.run import Message
from agentos.pipeline import InboundMessage, Pipeline
from agentos.sandbox.workspace import WorkspaceManager
from agentos.syscall.approval_registry import approval_registry


class CheckedSession(AsyncSession):
    """Expose overlapping session commits at the real parallel-tool call site."""

    committing = False

    async def commit(self):
        assert not self.committing, "overlapping commits on the run session"
        self.committing = True
        try:
            await asyncio.sleep(0.01)
            return await super().commit()
        finally:
            self.committing = False


async def test_parallel_approvals_serialize_run_persistence(tmp_path, monkeypatch):
    engine = SQLiteBackend().create_engine(f"sqlite+aiosqlite:///{tmp_path}/approvals.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)
    monkeypatch.setattr(settings, "yolo_mode", False)
    monkeypatch.setattr(settings, "hitl_timeout", 1)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(WorkspaceManager, "get_workspace_path", lambda self, aid: workspace)
    await db_module.init_db()

    existing_tasks = asyncio.all_tasks()
    pending_calls = []

    async def approve(event_type, payload):
        if event_type == "tool_call" and payload.get("status") == "pending_approval":
            pending_calls.append(payload["id"])
            approval_registry.resolve(payload["approval_id"], "approved", "test-operator")

    try:
        async with CheckedSession(engine, expire_on_commit=False) as db:
            config = AgentConfig(
                id="parallel-approval",
                name="Parallel Approval",
                model=ModelConfig(provider_id="test", name="scripted"),
                capabilities=[CapabilityGrant(name="write_file", require_approval=True)],
            )
            await create_agent(db, config)
            model = ScriptedModel(
                [
                    ScriptedResponse(
                        tool_calls=[
                            {
                                "id": f"call-{index}",
                                "name": "write_file",
                                "args": {"path": f"{index}.txt", "content": "approved"},
                            }
                            for index in range(2)
                        ]
                    ),
                    ScriptedResponse(content="Both files written."),
                ]
            )
            pipeline = Pipeline(db=db, harness=Harness(model=model))
            run = await asyncio.wait_for(
                pipeline.handle_inbound(
                    InboundMessage(
                        channel="dashboard_chat",
                        bot_id=config.id,
                        external_user_id="operator",
                        text="Write two files after approval.",
                        message_id=str(uuid.uuid4()),
                    ),
                    event_emitter=approve,
                ),
                timeout=10,
            )
            assert run.status == "completed"
            assert sorted(pending_calls) == ["call-0", "call-1"]
            messages = (
                await db.scalars(
                    select(Message).where(Message.run_id == run.id, Message.role == "tool_call")
                )
            ).all()
            assert {json.loads(message.content)["id"] for message in messages} == {
                "call-0",
                "call-1",
            }
            approvals = (
                await db.scalars(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id))
            ).all()
            assert len(approvals) == 2
            assert all(approval.status == "approved" for approval in approvals)
        async with factory() as probe:
            await probe.execute(text("BEGIN IMMEDIATE"))
            await probe.rollback()
    finally:
        new_tasks = asyncio.all_tasks() - existing_tasks - {asyncio.current_task()}
        for task in new_tasks:
            task.cancel()
        await asyncio.gather(*new_tasks, return_exceptions=True)
        await engine.dispose()
