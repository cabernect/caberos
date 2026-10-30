"""The terminal capability must tell the model which shell it is writing for."""

import sys
from unittest.mock import patch

from agentos.capabilities.tools.terminal import shell_dialect_note


def test_windows_description_says_commands_go_through_cmd_exe():
    """Found live: models default to POSIX habits (`ls`, `cat`, `$HOME`), which
    fail on Windows with 'not recognized'. The tool has to say it is cmd.exe."""
    with patch.object(sys, "platform", "win32"):
        note = shell_dialect_note()

    assert "cmd.exe" in note
    assert "powershell" in note


def test_posix_platforms_add_nothing():
    for platform in ("darwin", "linux"):
        with patch.object(sys, "platform", platform):
            assert shell_dialect_note() == ""
