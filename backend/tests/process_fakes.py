"""Synthetic subprocess pipes; no OS process, PID lookup, or signal is issued."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", *, returncode=0, hang=False, error=None):
        self.returncode = None if hang else returncode
        self.pid = 2**31 - 1
        self._exited = asyncio.Event()
        if not hang:
            self._exited.set()
        self.stdout = SimpleNamespace(read=AsyncMock(side_effect=[stdout, b""]))
        self.stderr = SimpleNamespace(read=AsyncMock(side_effect=[stderr, b""]))
        if hang:

            async def pending_read(size):
                await self._exited.wait()
                return b""

            self.stdout.read = AsyncMock(side_effect=pending_read)
            self.stderr.read = AsyncMock(side_effect=pending_read)
        if error is not None:
            self.stdout.read = AsyncMock(side_effect=error)

    async def wait(self):
        await self._exited.wait()
        return self.returncode

    def kill(self):
        self.returncode = -9
        self._exited.set()
