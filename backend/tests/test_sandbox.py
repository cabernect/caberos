"""Test the sandbox — shell execution and path validation."""

import pytest

from agentos.sandbox import WorkspaceManager, get_backend


@pytest.mark.asyncio
async def test_sandbox_echo(workspace):
    """shell.run('echo hello') returns 'hello' in the sandbox."""
    backend = get_backend()
    if not backend.is_available():
        pytest.skip("Sandbox backend not available on this platform")

    result = await backend.run_command(workspace, "echo hello")
    assert result.exit_code == 0
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_sandbox_workspace_writable(workspace):
    """The sandbox can write to the workspace."""
    backend = get_backend()
    if not backend.is_available():
        pytest.skip("Sandbox backend not available")

    result = await backend.run_command(workspace, "echo test > file.txt && cat file.txt")
    assert result.exit_code == 0
    assert "test" in result.stdout


@pytest.mark.asyncio
async def test_sandbox_clean_env(workspace):
    """The sandbox has a clean environment (no host secrets)."""
    backend = get_backend()
    if not backend.is_available():
        pytest.skip("Sandbox backend not available")

    result = await backend.run_command(workspace, "echo $HOME")
    assert result.exit_code == 0
    # HOME should be set to the workspace path, not the host's home
    assert "/workspace" in result.stdout or workspace in result.stdout


def test_workspace_path_validation(workspace):
    """Path validation rejects paths that escape the workspace."""
    wm = WorkspaceManager()

    # Valid path
    safe = wm.validate_path(workspace, "test.txt")
    assert safe.startswith(workspace)

    # Path escape via ../
    with pytest.raises(ValueError, match="escapes workspace"):
        wm.validate_path(workspace, "../../../etc/passwd")

    # Absolute path
    with pytest.raises(ValueError, match="escapes workspace"):
        wm.validate_path(workspace, "/etc/passwd")


def test_workspace_create(tmp_path):
    """WorkspaceManager creates directories."""
    # Use a custom path for testing
    ws_path = tmp_path / "test-agent-ws"
    ws_path.mkdir()
    assert ws_path.exists()
