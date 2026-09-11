"""Tests for MCP stdio command resolution — runtime PATH resolution."""

import os
from unittest.mock import patch

import pytest

from agentos.mcp.client import _resolve_stdio_command


def test_resolve_absolute_path():
    """Absolute paths are used as-is."""
    resolved, env = _resolve_stdio_command("/usr/bin/echo", {})
    assert resolved == "/usr/bin/echo"
    assert "PATH" not in env  # env unchanged


def test_resolve_command_on_path():
    """Commands on the current PATH resolve to full paths."""
    # 'ls' is on every Unix PATH
    resolved, env = _resolve_stdio_command("ls", {})
    assert os.path.isabs(resolved)
    assert "PATH" in env
    # Resolved dir should be prepended to PATH
    resolved_dir = os.path.dirname(resolved)
    assert env["PATH"].startswith(resolved_dir)


def test_resolve_command_not_found():
    """Missing commands raise an actionable RuntimeError."""
    with pytest.raises(RuntimeError, match="not found"):
        _resolve_stdio_command("nonexistent_command_xyz_123", {})


def test_resolve_command_with_custom_runtime_path():
    """CABEROS_MCP_RUNTIME_PATH is searched as a fallback."""
    with patch.dict(os.environ, {"CABEROS_MCP_RUNTIME_PATH": "/custom/runtime"}):
        with pytest.raises(RuntimeError, match="/custom/runtime"):
            _resolve_stdio_command("nonexistent_command_xyz_123", {})


def test_resolve_command_with_env_path():
    """env["PATH"] is used as the subprocess's PATH."""
    # Create a fake PATH with a fake command
    fake_bin = "/tmp/fake_bin_xyz"
    os.makedirs(fake_bin, exist_ok=True)
    fake_cmd = os.path.join(fake_bin, "fake_cmd")
    with open(fake_cmd, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_cmd, 0o755)

    try:
        env = {"PATH": fake_bin}
        resolved, updated_env = _resolve_stdio_command("fake_cmd", env)
        assert resolved == fake_cmd
        assert updated_env["PATH"].startswith(fake_bin)
    finally:
        os.unlink(fake_cmd)
        os.rmdir(fake_bin)


def test_resolve_command_fallback_dirs():
    """Fallback directories are searched when PATH doesn't contain the command."""
    # Temporarily add a fallback dir with a fake command
    fake_bin = "/tmp/fake_fallback_xyz"
    os.makedirs(fake_bin, exist_ok=True)
    fake_cmd = os.path.join(fake_bin, "fallback_cmd")
    with open(fake_cmd, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(fake_cmd, 0o755)

    try:
        # Patch _RUNTIME_DIRS to include our fake dir
        with patch(
            "agentos.mcp.client._RUNTIME_DIRS",
            ["/opt/homebrew/bin", "/usr/local/bin", fake_bin],
        ):
            resolved, env = _resolve_stdio_command("fallback_cmd", {})
            assert resolved == fake_cmd
            assert env["PATH"].startswith(fake_bin)
    finally:
        os.unlink(fake_cmd)
        os.rmdir(fake_bin)
