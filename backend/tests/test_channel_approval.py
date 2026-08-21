"""Tests for explicit approval policy for external channels (v0.1.3 Trust Bundle).

Covers:
- auto_approve executes without waiting
- deny blocks approval-required tools and audits the denial
- operator creates a pending approval visible in the dashboard
- capabilities not requiring approval remain executable
- channel policy applies only to the configured channel
- a missing policy defaults to deny for newly configured channels
"""

import pytest
from sqlalchemy import select

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.models.approval import ApprovalRequest
from agentos.models.audit import AuditRecord
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


@pytest.fixture(autouse=True)
def _setup_caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


def _make_agent_config(caps: list[str], approval_caps: list[str] | None = None) -> AgentConfig:
    """Build an agent config. approval_caps lists capabilities that require approval."""
    approval_set = approval_caps or []
    return AgentConfig(
        id="test-agent",
        name="Test Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c, require_approval=(c in approval_set)) for c in caps],
    )


def _make_channel_session(channel: str = "telegram"):
    from types import SimpleNamespace

    return SimpleNamespace(
        contact_id="contact-1",
        id="test-session-id",
        channel=channel,
    )


class TestChannelApprovalPolicy:
    """Tests for explicit channel approval policies."""

    async def test_auto_approve_executes_without_waiting(self, db, workspace):
        """auto_approve executes approval-required tools without waiting."""
        import os

        # terminal requires approval — write a file first so we can test
        # with a non-approval tool too
        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        agent_config = _make_agent_config(["read_file", "terminal"], approval_caps=["terminal"])
        session = _make_channel_session("telegram")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        handler._channel_approval_policy = "auto_approve"

        # terminal normally requires approval, but auto_approve should bypass
        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        # Should be allowed (auto-approved). The terminal tool may succeed or
        # fail depending on sandbox, but it should not be denied for approval.
        assert result.allowed is True
        assert result.denied_reason is None

    async def test_deny_blocks_approval_required_tools(self, db, workspace):
        """deny blocks approval-required tools and audits the denial."""
        agent_config = _make_agent_config(["terminal"], approval_caps=["terminal"])
        session = _make_channel_session("telegram")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        handler._channel_approval_policy = "deny"

        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
        assert (
            "denied" in (result.denied_reason or "").lower()
            or "policy" in (result.denied_reason or "").lower()
        )

        # Audit record should exist
        await db.commit()
        audit_result = await db.execute(
            select(AuditRecord).where(
                AuditRecord.capability_name == "terminal",
                AuditRecord.allowed == False,  # noqa: E712
            )
        )
        audits = audit_result.scalars().all()
        assert len(audits) >= 1

    async def test_operator_creates_pending_approval(self, db, workspace):
        """operator policy creates a pending approval visible in the dashboard."""
        agent_config = _make_agent_config(["terminal"], approval_caps=["terminal"])
        session = _make_channel_session("telegram")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        handler._channel_approval_policy = "operator"

        # Use a short timeout so the test doesn't hang
        import agentos.config as config_module

        original_timeout = config_module.settings.hitl_timeout
        config_module.settings.hitl_timeout = 1  # 1 second

        try:
            result = await handler.mediate(
                call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
                session=session,
                agent_config=agent_config,
                run_id="run-1",
            )
        finally:
            config_module.settings.hitl_timeout = original_timeout

        # Should be denied (timed out waiting for approval)
        assert result.allowed is False

        # An approval request should have been created
        await db.commit()
        approval_result = await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.capability_name == "terminal")
        )
        approvals = approval_result.scalars().all()
        assert len(approvals) >= 1

    async def test_non_approval_caps_remain_executable(self, db, workspace):
        """Capabilities not requiring approval remain executable regardless of policy."""
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        agent_config = _make_agent_config(["read_file"])
        session = _make_channel_session("telegram")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        handler._channel_approval_policy = "deny"

        # read_file does not require approval — should work even with deny policy
        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["content"] == "hello world"

    async def test_policy_applies_only_to_configured_channel(self, db, workspace):
        """Channel policy applies only to the configured channel.

        A dashboard session (channel=None) should not be affected by channel
        approval policy.
        """
        import os

        test_file = os.path.join(workspace, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        from types import SimpleNamespace

        dashboard_session = SimpleNamespace(
            contact_id="contact-1",
            id="dash-session",
            channel=None,
        )

        agent_config = _make_agent_config(["read_file"])
        handler = SyscallHandler(db=db, workspace_path=workspace)
        handler._channel_approval_policy = "deny"  # should not apply to dashboard

        result = await handler.mediate(
            call=ToolCall(id="1", name="read_file", args={"path": "test.txt"}),
            session=dashboard_session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True

    async def test_missing_policy_defaults_to_deny(self, db, workspace):
        """A missing policy defaults to deny for newly configured channels."""
        agent_config = _make_agent_config(["terminal"], approval_caps=["terminal"])
        session = _make_channel_session("telegram")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        # No _channel_approval_policy set — should default to deny

        result = await handler.mediate(
            call=ToolCall(id="1", name="terminal", args={"command": "echo hi"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
