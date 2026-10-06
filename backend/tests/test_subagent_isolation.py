"""Tests for sub-agent capability isolation (v0.1.3 Trust Bundle).

Covers:
- parent grants read_file, sub-agent requests terminal → denied
- parent grants {read_file}, sub-agent declares {read_file, terminal} →
  effective set is {read_file}
- nested sub-agent capabilities can only shrink
- denied calls produce an audit record with sub_agent_id
- an omitted sub-agent capability set does not mean unrestricted access
"""

import pytest

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


def test_subagent_tool_imports_cleanly():
    """Regression for `No module named 'agentos.capabilities.tools.protocol'`.

    The restricted sub-agent path must import cleanly — this is what the
    packaged gateway broke on when a stale module was referenced.
    """
    import importlib.util

    import agentos.capabilities.tools.subagent as subagent_mod

    assert callable(subagent_mod.register_subagent_tools)
    # No stale protocol module under capabilities.tools
    assert importlib.util.find_spec("agentos.capabilities.tools.protocol") is None
    # The real protocol lives in agentos.syscall.
    assert importlib.util.find_spec("agentos.syscall.protocol") is not None


@pytest.fixture(autouse=True)
def _setup_caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


def _make_agent_config(caps: list[str]) -> AgentConfig:
    return AgentConfig(
        id="parent-agent",
        name="Parent Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c) for c in caps],
    )


def _make_sub_agent_config(caps: list[str]) -> AgentConfig:
    return AgentConfig(
        id="sub-agent-1",
        name="Sub Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c) for c in caps],
    )


def _make_session():
    from types import SimpleNamespace

    return SimpleNamespace(contact_id="contact-1", id="test-session-id", channel=None)


class TestSubAgentCapabilityIsolation:
    """Tests for sub-agent capability isolation."""

    async def test_sub_agent_denied_capability_not_in_parent(self, db, workspace):
        """Parent grants read_file, sub-agent requests terminal → denied."""
        # Write a test file so terminal is the only thing being tested
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        parent_config = _make_agent_config(["read_file"])
        sub_config = _make_sub_agent_config(["terminal"])
        session = _make_session()

        handler = SyscallHandler(db=db, workspace_path=workspace)

        # The sub-agent tries to use terminal, which the parent doesn't have
        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-1",
            parent_config=parent_config,
        )

        assert result.allowed is False
        assert "not granted" in (result.denied_reason or "") or "parent" in (
            result.denied_reason or ""
        )

    async def test_sub_agent_effective_set_intersected(self, db, workspace):
        """Parent grants {read_file}, sub-agent declares {read_file, terminal} →
        effective set is {read_file}. Terminal is denied, read_file is allowed."""
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        parent_config = _make_agent_config(["read_file"])
        # Sub-agent declares both read_file and terminal
        sub_config = _make_sub_agent_config(["read_file", "terminal"])
        session = _make_session()

        handler = SyscallHandler(db=db, workspace_path=workspace)

        # read_file should be allowed (in both parent and sub)
        result_read = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-1",
            parent_config=parent_config,
        )
        assert result_read.allowed is True
        assert result_read.output["content"] == "hello world"

        # terminal should be denied (not in parent)
        result_term = await handler.mediate(
            call=ToolCall(id="2", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-1",
            parent_config=parent_config,
        )
        assert result_term.allowed is False

    async def test_nested_sub_agent_capabilities_shrink(self, db, workspace):
        """Nested sub-agent capabilities can only shrink.

        A sub-agent of a sub-agent cannot have more capabilities than the
        first sub-agent's effective set.
        """
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        # Parent has read_file and terminal
        # First sub has read_file only (subset of parent)
        sub1_config = _make_sub_agent_config(["read_file"])
        # Nested sub tries to use terminal (not in sub1's effective set)
        sub2_config = AgentConfig(
            id="sub-agent-2",
            name="Nested Sub",
            model=ModelConfig(provider_id="test-provider", name="test-model"),
            capabilities=[CapabilityGrant(name="terminal")],
        )
        session = _make_session()

        handler = SyscallHandler(db=db, workspace_path=workspace)

        # Nested sub tries terminal — should be denied because sub1 doesn't have it
        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=sub2_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-2",
            parent_config=sub1_config,
        )
        assert result.allowed is False

    async def test_denied_call_produces_audit_with_sub_agent_id(self, db, workspace):
        """Denied sub-agent calls produce an audit record with sub_agent_id."""
        from sqlalchemy import select

        from agentos.models.audit import AuditRecord

        parent_config = _make_agent_config(["read_file"])
        sub_config = _make_sub_agent_config(["terminal"])
        session = _make_session()

        handler = SyscallHandler(db=db, workspace_path=workspace)

        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-audit-1",
            parent_config=parent_config,
        )

        assert result.allowed is False

        # Check audit record
        await db.commit()
        audit_result = await db.execute(
            select(AuditRecord).where(AuditRecord.sub_agent_id == "sub-audit-1")
        )
        audits = audit_result.scalars().all()
        assert len(audits) >= 1
        assert audits[0].allowed is False
        assert audits[0].sub_agent_id == "sub-audit-1"

    async def test_omitted_capabilities_does_not_mean_unrestricted(self, db, workspace):
        """An omitted sub-agent capability set does not mean unrestricted access.

        If a sub-agent has capabilities=None (meaning "all tools"), it should
        still be intersected with the parent's effective set.
        """
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        parent_config = _make_agent_config(["read_file"])
        # Sub-agent with capabilities=None (all tools)
        sub_config = AgentConfig(
            id="sub-agent-3",
            name="Sub Agent",
            model=ModelConfig(provider_id="test-provider", name="test-model"),
            capabilities=None,  # all tools
        )
        session = _make_session()

        handler = SyscallHandler(db=db, workspace_path=workspace)

        # read_file should be allowed (in parent)
        result_read = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-3",
            parent_config=parent_config,
        )
        assert result_read.allowed is True

        # terminal should be denied (not in parent, even though sub has all)
        result_term = await handler.mediate(
            call=ToolCall(id="2", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=sub_config,
            run_id="run-1",
            is_sub_agent=True,
            sub_agent_id="sub-3",
            parent_config=parent_config,
        )
        assert result_term.allowed is False


class TestSubAgentModelOverride:
    """Regression for B21 — model.provider_id passed as a vendor name
    ('openai') used to reach LiteLLM as a literal id and fail
    'Provider openai not found'. The resolver now accepts a bare id, resolves
    a unique name/type match, and otherwise returns a corrective error."""

    async def _resolve(self, db, ref):
        from agentos.capabilities.tools.subagent import _resolve_provider_ref

        return await _resolve_provider_ref(db, ref)

    async def test_exact_provider_id_wins(self, db):
        from agentos.models.provider import Provider

        db.add(Provider(id="prov-1", name="My OpenAI", type="openai"))
        db.add(Provider(id="prov-2", name="Other", type="openai"))
        await db.commit()

        assert await self._resolve(db, "prov-1") == "prov-1"

    async def test_vendor_type_resolves_when_unique(self, db):
        from agentos.models.provider import Provider

        db.add(Provider(id="prov-1", name="My OpenAI", type="openai"))
        db.add(Provider(id="prov-2", name="Claude", type="anthropic"))
        await db.commit()

        assert await self._resolve(db, "anthropic") == "prov-2"

    async def test_provider_name_resolves_case_insensitive(self, db):
        from agentos.models.provider import Provider

        db.add(Provider(id="prov-1", name="Opencode Zen", type="openai"))
        await db.commit()

        assert await self._resolve(db, "opencode zen") == "prov-1"

    async def test_ambiguous_type_returns_corrective_error(self, db):
        from agentos.models.provider import Provider

        db.add(Provider(id="prov-1", name="OpenAI A", type="openai"))
        db.add(Provider(id="prov-2", name="OpenAI B", type="openai"))
        await db.commit()

        result = await self._resolve(db, "openai")
        assert isinstance(result, dict)
        assert "ambiguous" in result["error"]
        assert "prov-1" in result["error"] and "prov-2" in result["error"]
        assert "omit 'model'" in result["error"]

    async def test_unknown_ref_returns_corrective_error(self, db):
        from agentos.models.provider import Provider

        db.add(Provider(id="prov-1", name="My OpenAI", type="openai"))
        await db.commit()

        result = await self._resolve(db, "anthropic")
        assert isinstance(result, dict)
        assert "not a configured provider" in result["error"]
        assert "prov-1" in result["error"]
        assert "omit 'model'" in result["error"]

    async def test_non_string_ref_returns_corrective_error(self, db):
        result = await self._resolve(db, 42)
        assert isinstance(result, dict)
        assert "non-empty string" in result["error"]


class TestSubAgentWrapperForwarding:
    """Regression for B22 — _SubAgentSyscallHandler.mediate must accept and
    forward every kwarg harness/loop.py passes to mediate() (approval_batch,
    trigger, …). Exercises a sub-agent tool call end-to-end with fakes."""

    async def test_wrapper_accepts_and_forwards_loop_kwargs(self, db, workspace):
        from types import SimpleNamespace

        from agentos.capabilities.tools.subagent import _execute_subagent

        forwarded: dict = {}

        class FakeParentHandler:
            def __init__(self, db_session, ws):
                self.db = db_session
                self.workspace_path = ws
                self.sandbox_mode = "unrestricted"

            async def mediate(self, **kwargs):
                forwarded.update(kwargs)
                return SimpleNamespace(allowed=True, output={})

        class FakeHarness:
            async def run(self, *, syscall_handler, agent_config, session, **kw):
                # Mirror loop.py's dispatch kwargs on a sub-agent tool call
                await syscall_handler.mediate(
                    call="call-1",
                    session=session,
                    agent_config=agent_config,
                    run_id="ignored",
                    event_emitter=None,
                    capability_catalog=None,
                    approval_batch="BATCH-OBJ",
                    trigger="scheduled",
                )
                return SimpleNamespace(
                    final_answer="done",
                    total_turns=1,
                    tokens_in=1,
                    tokens_out=1,
                    total_cost=0.0,
                    status="completed",
                )

        parent = AgentConfig(
            id="parent",
            name="P",
            model=ModelConfig(provider_id="prov", name="m"),
        )
        result = await _execute_subagent(
            "sub-x",
            {"task": "do a thing"},
            workspace,
            {
                "parent_config": parent,
                "_spawn_context": {
                    "harness": FakeHarness(),
                    "syscall_handler": FakeParentHandler(db, workspace),
                    "session": _make_session(),
                    "run_id": "run-1",
                },
            },
        )

        assert result["result"] == "done"
        # Both new kwargs reached the real mediator…
        assert forwarded["approval_batch"] == "BATCH-OBJ"
        assert forwarded["trigger"] == "scheduled"
        # …and the wrapper stamped the call as a sub-agent call under the
        # parent's run, not the sub-agent's own run_id.
        assert forwarded["is_sub_agent"] is True
        assert forwarded["sub_agent_id"] == "sub-x"
        assert forwarded["run_id"] == "run-1"
