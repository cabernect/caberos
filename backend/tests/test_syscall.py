"""Tests for the real syscall layer (ticket 03 — D10, D11, D18)."""

import pytest

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.syscall.mediator import SyscallHandler, reduce_result
from agentos.syscall.protocol import ToolCall


@pytest.fixture(autouse=True)
def _setup_caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


def _make_agent_config(caps: list[str]) -> AgentConfig:
    return AgentConfig(
        id="test-agent",
        name="Test Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c) for c in caps],
    )


def _make_session(contact_id: str):
    """Make a simple session-like object."""
    from types import SimpleNamespace

    return SimpleNamespace(contact_id=contact_id, id="test-session-id")


class TestReduceResult:
    def test_small_result_passes_through(self):
        result = {"stdout": "hello", "exit_code": 0}
        assert reduce_result(result) == result

    def test_large_result_is_truncated(self):
        big = {"content": "x" * 10000}
        reduced = reduce_result(big)
        assert reduced is not None
        assert isinstance(reduced, dict)
        assert reduced.get("truncated") is True
        assert "preview" in reduced

    def test_none_passes_through(self):
        assert reduce_result(None) is None


class TestSyscallHandler:
    async def test_read_file_success(self, db, workspace):
        # Write a test file
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["read_file"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["content"] == "hello world"

    async def test_read_file_path_escape_rejected(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["read_file"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "../../../etc/passwd"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
        assert "execution error" in (result.denied_reason or "")

    async def test_not_granted_capability_denied(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        # Agent has no capabilities granted
        agent_config = _make_agent_config([])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
        assert result.denied_reason == "not granted"

    async def test_capability_not_found_denied(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["nonexistent.cap"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="nonexistent.cap", args={}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
        assert result.denied_reason == "capability not found"

    async def test_terminal_success(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["terminal"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hello"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert "hello" in result.output["stdout"]

    async def test_write_file_then_read(self, db, workspace):
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["write_file", "read_file"])
        session = _make_session("contact-1")

        # Write
        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="write_file",
                args={"path": "output.txt", "content": "written content"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )
        assert result.allowed is True
        assert result.output["success"] is True

        # Read back
        result = await handler.mediate(
            call=ToolCall(id="2", name="read_file", args={"path": "output.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )
        assert result.allowed is True
        assert result.output["content"] == "written content"

    async def test_search_files(self, db, workspace):
        import os

        # Create some files
        with open(os.path.join(workspace, "a.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(workspace, "b.txt"), "w") as f:
            f.write("b")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["search_files"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="search_files", args={"mode": "list", "path": "."}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        names = [e["name"] for e in result.output["entries"]]
        assert "a.txt" in names
        assert "b.txt" in names

    async def test_audit_record_written(self, db, workspace):
        from sqlalchemy import select

        from agentos.models.audit import AuditRecord

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["terminal"])
        session = _make_session("contact-1")

        await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo test"}),
            session=session,
            agent_config=agent_config,
            run_id="run-audit-test",
        )

        # Check audit record
        result = await db.execute(select(AuditRecord).where(AuditRecord.run_id == "run-audit-test"))
        records = result.scalars().all()
        assert len(records) == 1
        assert records[0].allowed is True
        assert records[0].capability_name == "terminal"

    async def test_denied_audit_record_written(self, db, workspace):
        from sqlalchemy import select

        from agentos.models.audit import AuditRecord

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config([])  # no capabilities
        session = _make_session("contact-1")

        await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo test"}),
            session=session,
            agent_config=agent_config,
            run_id="run-deny-test",
        )

        result = await db.execute(select(AuditRecord).where(AuditRecord.run_id == "run-deny-test"))
        records = result.scalars().all()
        assert len(records) == 1
        assert records[0].allowed is False
        assert records[0].denied_reason == "not granted"

    async def test_result_reduction_applied(self, db, workspace):
        """D18 — oversized results are reduced before entering model context."""
        import os

        # Create a file with lots of content
        big_content = "x" * 10000
        with open(os.path.join(workspace, "big.txt"), "w") as f:
            f.write(big_content)

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config(["read_file"])
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "big.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        # The output should be reduced (truncated)
        assert isinstance(result.output, dict)
        assert result.output.get("truncated") is True


class TestNoneCapabilities:
    """Tests for capabilities=None (all tools enabled) vs [] (none)."""

    async def test_none_capabilities_allows_any_tool(self, db, workspace):
        """capabilities=None means all tools are granted."""
        import os

        with open(os.path.join(workspace, "test.txt"), "w") as f:
            f.write("hello")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = AgentConfig(
            id="test-agent",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=None,  # all tools enabled
        )
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )
        assert result.allowed is True
        assert result.output["content"] == "hello"

    async def test_empty_capabilities_denies_all(self, db, workspace):
        """capabilities=[] means no tools are granted."""
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = AgentConfig(
            id="test-agent",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=[],  # no tools
        )
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )
        assert result.allowed is False
        assert result.denied_reason == "not granted"

    async def test_none_capabilities_uses_cap_def_approval(self, db, workspace):
        """When capabilities=None, the approval check doesn't crash on None.

        We use datetime_now (no approval required) to verify the code path
        that looks up the grant in agent_config.capabilities handles None
        without raising 'NoneType is not iterable'.
        """
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = AgentConfig(
            id="test-agent",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=None,  # all tools, no per-grant overrides
        )
        session = _make_session("contact-1")

        # datetime_now doesn't require approval, so this should succeed.
        # The key is that the grant lookup at line 128 doesn't crash on None.
        result = await handler.mediate(
            call=ToolCall(id="1", name="datetime_now", args={}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )
        assert result.allowed is True
        assert "iso" in result.output


class TestGetEnabledCapabilities:
    """Tests for get_enabled_capabilities in context.py."""

    def test_none_returns_all_tools(self):
        from agentos.capabilities.builtin import register_builtin_capabilities
        from agentos.capabilities.registry import registry
        from agentos.harness.context import get_enabled_capabilities

        registry._caps.clear()
        register_builtin_capabilities()

        config = AgentConfig(
            id="test",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=None,
        )
        caps = get_enabled_capabilities(config)
        assert len(caps) > 0
        assert "read_file" in caps
        assert "terminal" in caps
        assert "run_subagent" in caps

        registry._caps.clear()

    def test_empty_returns_no_tools(self):
        from agentos.capabilities.builtin import register_builtin_capabilities
        from agentos.capabilities.registry import registry
        from agentos.harness.context import get_enabled_capabilities

        registry._caps.clear()
        register_builtin_capabilities()

        config = AgentConfig(
            id="test",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=[],
        )
        caps = get_enabled_capabilities(config)
        assert caps == []

        registry._caps.clear()

    def test_explicit_list_returns_only_those(self):
        from agentos.capabilities.builtin import register_builtin_capabilities
        from agentos.capabilities.registry import registry
        from agentos.harness.context import get_enabled_capabilities

        registry._caps.clear()
        register_builtin_capabilities()

        config = AgentConfig(
            id="test",
            name="Test",
            model=ModelConfig(provider_id="test", name="test"),
            capabilities=[CapabilityGrant(name="read_file"), CapabilityGrant(name="write_file")],
        )
        caps = get_enabled_capabilities(config)
        assert set(caps) == {"read_file", "write_file"}

        registry._caps.clear()
