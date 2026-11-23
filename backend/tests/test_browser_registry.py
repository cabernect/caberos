import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.browser import registry as module
from agentos.browser.cdp import BrowserError
from agentos.browser.registry import BrowserRegistry


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(module, "find_browser_binary", lambda: "/fake/chrome")
    browsers = []

    async def open_page(*args, **kwargs):
        await asyncio.sleep(0)
        return MagicMock()

    def create(*args, **kwargs):
        browser = MagicMock()
        browser.alive.return_value = True
        browser.open = AsyncMock(side_effect=open_page)
        browser.observe = AsyncMock(return_value=MagicMock())
        browser.navigate = AsyncMock()
        browser.close = AsyncMock()
        browser.fell_back = False
        browsers.append(browser)
        return browser

    monkeypatch.setattr(module, "BrowserSession", create)
    reg = BrowserRegistry()
    monkeypatch.setattr(reg, "_ensure_reaper", lambda: None)
    return reg, browsers


async def test_reuse_cannot_cross_agent_boundary(registry):
    reg, browsers = registry
    await reg.get_or_open("https://example.com", "owner", "chat", "r1")
    with pytest.raises(BrowserError):
        await reg.get_or_open("https://example.com", "other", "chat", "r2")
    browsers[0].navigate.assert_not_awaited()


async def test_wrong_session_cannot_fall_back_to_run(registry):
    reg, _ = registry
    await reg.get_or_open("https://example.com", "owner", "chat", "r1")
    with pytest.raises(BrowserError):
        reg.get_owned("r1", "owner", "wrong-chat")


async def test_stop_preserves_conversation_browser_but_cleans_sessionless(registry):
    reg, browsers = registry
    await reg.get_or_open("https://example.com", "owner", "chat", "r1")
    assert not await reg.close_for_run("r1")
    assert reg.get_owned("r2", "owner", "chat") is browsers[0]
    await reg.get_or_open("https://example.com", "owner", None, "background")
    assert await reg.close_for_run("background")
    browsers[0].close.assert_not_awaited()
    browsers[1].close.assert_awaited_once()


async def test_concurrent_open_creates_only_one_browser(registry):
    reg, browsers = registry
    await asyncio.gather(
        reg.get_or_open("https://example.com", "owner", "chat", "r1"),
        reg.get_or_open("https://example.com", "owner", "chat", "r2"),
    )
    assert len(browsers) == 1


async def test_close_checks_agent_and_session(registry):
    reg, browsers = registry
    await reg.get_or_open("https://example.com", "owner", "chat", "r1")
    with pytest.raises(BrowserError):
        await reg.close_owned("r1", "other", "chat")
    assert not await reg.close_owned("r1", "owner", "wrong-chat")
    browsers[0].close.assert_not_awaited()
    assert await reg.close_owned("r2", "owner", "chat")


async def test_concurrent_profile_acquisition_is_exclusive(registry, monkeypatch, tmp_path):
    reg, browsers = registry
    monkeypatch.setattr(module, "_profiles_root", lambda: tmp_path)
    results = await asyncio.gather(
        reg.get_or_open("https://example.com", "owner", "chat1", "r1", profile="work"),
        reg.get_or_open("https://example.com", "owner", "chat2", "r2", profile="work"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, BrowserError) for result in results) == 1
    assert len(browsers) == 1


async def test_operations_serialize_and_close_waits(registry):
    reg, browsers = registry
    await reg.get_or_open("https://example.com", "owner", "chat", "r1")
    async with reg.owned("r2", "owner", "chat"):
        closing = asyncio.create_task(reg.close_owned("r2", "owner", "chat"))
        await asyncio.sleep(0)
        browsers[0].close.assert_not_awaited()
    assert await closing


async def test_run_and_session_keys_do_not_collide(registry):
    reg, browsers = registry
    await reg.get_or_open("https://example.com", "owner", "run:background", "r1")
    await reg.get_or_open("https://example.com", "owner", None, "background")
    assert len(browsers) == 2
