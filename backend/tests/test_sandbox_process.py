"""Shared execution completion contract; synthetic processes only."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock

import pytest
from tests.process_fakes import FakeProcess

from agentos.sandbox import base as sandbox_base
from agentos.sandbox import process
from agentos.sandbox.process import collect_process, drain_output


async def test_collect_preserves_output_exit_status_and_replacement_decoding():
    proc = FakeProcess(b"out\xff", b"err", returncode=7)
    cleanup = AsyncMock()
    result = await collect_process(proc, timeout=1, started_at=time.monotonic(), cleanup=cleanup)
    assert (result.stdout, result.stderr, result.exit_code) == ("out\ufffd", "err", 7)
    assert result.duration_ms >= 0
    cleanup.assert_not_awaited()


async def test_timeout_requests_cleanup_before_returning_the_existing_error_shape():
    proc = FakeProcess(error=TimeoutError)
    cleanup = AsyncMock()
    result = await collect_process(proc, timeout=3, started_at=time.monotonic(), cleanup=cleanup)
    cleanup.assert_awaited_once_with(proc)
    assert (result.stdout, result.stderr, result.exit_code) == (
        "",
        "Command timed out after 3s",
        -1,
    )


@pytest.mark.parametrize("error", [asyncio.CancelledError, OSError])
async def test_interruption_requests_cleanup_and_propagates(error):
    proc = FakeProcess(error=error)
    cleanup = AsyncMock()
    with pytest.raises(error):
        await collect_process(proc, timeout=1, started_at=time.monotonic(), cleanup=cleanup)
    cleanup.assert_awaited_once_with(proc)


async def test_cleanup_failure_is_not_reported_as_successful_completion():
    proc = FakeProcess(error=TimeoutError)
    with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
        await collect_process(
            proc,
            timeout=1,
            started_at=time.monotonic(),
            cleanup=AsyncMock(side_effect=RuntimeError("synthetic cleanup failure")),
        )


async def test_both_streams_are_bounded_and_the_rest_is_drained(monkeypatch):
    monkeypatch.setattr(process, "OUTPUT_CAP_BYTES", 4)
    proc = FakeProcess(b"12345", b"abcde")
    cleanup = AsyncMock()
    result = await collect_process(proc, timeout=1, started_at=time.monotonic(), cleanup=cleanup)
    assert (result.stdout, result.stderr, result.truncated) == ("1234", "abcd", True)
    assert proc.stdout.read.await_count == 2
    assert proc.stderr.read.await_count == 2
    cleanup.assert_not_awaited()


async def test_exact_limit_does_not_claim_truncation(monkeypatch):
    monkeypatch.setattr(process, "OUTPUT_CAP_BYTES", 4)
    result = await collect_process(
        FakeProcess(b"1234"), timeout=1, started_at=time.monotonic(), cleanup=AsyncMock()
    )
    assert result.stdout == "1234"
    assert result.truncated is False


async def test_sink_failure_keeps_draining_and_reports_lost_output():
    proc = FakeProcess(b"synthetic")
    progress = []

    def failed_write(chunk):
        raise OSError("synthetic full disk")

    truncated = await drain_output(
        proc.stdout, failed_write, progress=lambda n, lost: progress.append((n, lost))
    )
    assert truncated
    assert progress == [(9, True)]
    assert proc.stdout.read.await_count == 2


async def test_real_deadline_requests_cleanup_with_readers_still_active():
    proc = FakeProcess(hang=True)

    async def cleanup(child):
        assert proc.stdout.read.await_count == 1
        child.kill()
        await child.wait()

    result = await asyncio.wait_for(
        collect_process(proc, timeout=0.01, started_at=time.monotonic(), cleanup=cleanup),
        timeout=1,
    )
    assert result.exit_code == -1
    assert "timed out" in result.stderr


async def test_cleanup_never_signals_an_inherited_parent_group(monkeypatch):
    proc = FakeProcess(hang=True)
    signals = []
    monkeypatch.setattr(sandbox_base.sys, "platform", "linux")
    monkeypatch.setattr(sandbox_base.os, "getpgid", lambda pid: 12345, raising=False)
    kill_group = Mock()
    monkeypatch.setattr(sandbox_base.os, "killpg", kill_group, raising=False)

    def terminate(signal):
        signals.append(signal)
        proc.kill()

    proc.send_signal = terminate
    await sandbox_base.kill_process_group(proc, grace=0.01)
    kill_group.assert_not_called()
    assert len(signals) == 1


async def test_cleanup_waits_are_bounded_even_if_the_process_does_not_reap(monkeypatch):
    proc = FakeProcess(hang=True)
    monkeypatch.setattr(sandbox_base.sys, "platform", "linux")
    monkeypatch.setattr(sandbox_base.os, "getpgid", lambda pid: pid, raising=False)
    kill_group = Mock()
    monkeypatch.setattr(sandbox_base.os, "killpg", kill_group, raising=False)
    await asyncio.wait_for(sandbox_base.kill_process_group(proc, grace=0.001), timeout=1)
    assert kill_group.call_count == 2
    assert proc.returncode is None
