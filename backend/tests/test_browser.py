"""W4 Browser module — CDP session + capabilities.

Live tests launch the real managed runtime against a local dynamic page and
are skipped when no Chromium binary is discoverable (CI without a browser).
Unit tests cover the observation machinery and honest error paths without a
browser.
"""

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

from agentos.browser.cdp import BrowserError, BrowserSession, Element, Observation
from agentos.browser.registry import BrowserRegistry
from agentos.browser.runtime import find_browser_binary
from agentos.capabilities.tools.browser import (
    browser_act,
    browser_close,
    browser_observe,
    browser_open,
)

SPIKE_PAGE = Path(__file__).parents[2] / "scripts" / "spike_browser" / "page.html"

_browser = find_browser_binary()
needs_browser = pytest.mark.skipif(_browser is None, reason="no managed browser runtime available")

PAGE_HTML = """<!DOCTYPE html><html><head><title>t</title></head><body>
<div id="app">boot</div><script>
document.getElementById("app").innerHTML =
  '<h1>Hi</h1><button id="b">Count: 0</button><input id="i" aria-label="box">';
let n = 0;
document.getElementById("b").onclick = () =>
  document.getElementById("b").textContent = "Count: " + (++n);
</script></body></html>"""


def _serve(tmp_path: Path) -> tuple[http.server.HTTPServer, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "index.html").write_text(PAGE_HTML)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}/index.html"


# --- unit: observation machinery -------------------------------------------


def test_observation_serializes_bounded():
    obs = Observation(
        url="http://x",
        title="T",
        elements=[Element(ref="e1", role="button", name="Go")],
    )
    text = obs.serialize()
    assert "url: http://x" in text and "e1 button 'Go'" in text


def test_observation_delta_reports_changes():
    a = Observation(
        url="u",
        title="t",
        elements=[
            Element(ref="e1", role="button", name="A"),
            Element(ref="e2", role="link", name="B"),
        ],
    )
    b = Observation(
        url="u",
        title="t",
        elements=[
            Element(ref="e1", role="button", name="A2"),
            Element(ref="e3", role="link", name="C"),
        ],
    )
    d = b.delta(a)
    assert "~ e1 button 'A2'" in d
    assert "+ e3 link 'C'" in d
    assert "- e2 link 'B'" in d


def test_observation_delta_no_change():
    a = Observation(url="u", title="t", elements=[Element(ref="e1", role="button", name="A")])
    assert a.delta(a) == "(no change)"


def test_runtime_status_honest(monkeypatch):
    from agentos.browser import runtime

    monkeypatch.setenv("AGENTOS_BROWSER_BINARY", "/nonexistent/chrome")
    monkeypatch.setattr(runtime, "_playwright_cache_roots", lambda: [Path("/nonexistent")])
    status = runtime.runtime_status()
    assert status["status"] == "runtime_unavailable"


# --- unit: capability error paths -------------------------------------------


async def test_browser_observe_without_session_errors():
    with pytest.raises(BrowserError, match="no open browser session"):
        await browser_observe({}, agent_id="a", run_id="missing-run")


async def test_browser_close_without_session_is_honest():
    result = await browser_close({}, agent_id="a", run_id="missing-run")
    assert result == {"closed": False}


# --- live: real browser ------------------------------------------------------


@pytest.fixture
async def live_session(tmp_path):
    httpd, url = _serve(tmp_path)
    session = BrowserSession(_browser, tmp_path / "profile")
    (tmp_path / "profile").mkdir()
    try:
        obs = await session.open(url)
        yield session, obs
    finally:
        await session.close()
        httpd.shutdown()


@needs_browser
async def test_live_open_returns_semantic_observation(live_session):
    session, obs = live_session
    assert obs.url.endswith("index.html")
    names = [e.name for e in obs.elements]
    assert any("Count" in n for n in names)
    assert all(e.ref.startswith("e") for e in obs.elements)


@needs_browser
async def test_live_act_returns_delta_not_full_obs(live_session):
    session, obs = live_session
    button = next(e for e in obs.elements if "Count" in e.name)
    delta = await session.act("click", button.ref)
    assert "Count: 1" in delta
    assert "url:" not in delta  # delta, not a re-serialized observation


@needs_browser
async def test_live_type_and_extract(live_session):
    session, obs = live_session
    box = next(e for e in obs.elements if e.role == "textbox")
    await session.act("type", box.ref, "hello")
    out = await session.extract("document.getElementById('i').value")
    assert json.loads(out) == "hello"


@needs_browser
async def test_live_refs_die_with_page_state(live_session, tmp_path):
    """After navigation, stale refs fail honestly rather than acting wrong."""
    session, obs = live_session
    button = next(e for e in obs.elements if "Count" in e.name)
    await session.navigate("about:blank")
    with pytest.raises(BrowserError):
        await session.act("click", button.ref)


@needs_browser
async def test_live_registry_ownership_and_cleanup(tmp_path):
    """One run owns its session; another run can't drive it; close works."""
    httpd, url = _serve(tmp_path / "srv")
    reg = BrowserRegistry()
    try:
        session, result = await reg.get_or_open(url, agent_id="a1", session_id="s1", run_id="r1")
        assert "Count" in result
        assert reg.get_owned("r1", "a1") is session
        with pytest.raises(BrowserError):
            reg.get_owned("r1", "other-agent")
        assert await reg.close_for_run("r1") is True
        assert not session.alive()
        assert await reg.close_for_run("r1") is False
    finally:
        await reg.shutdown_all()
        httpd.shutdown()


@needs_browser
async def test_live_browser_open_capability_roundtrip(tmp_path):
    """The capability path: open → act → close through the tool surface."""
    httpd, url = _serve(tmp_path / "srv")
    try:
        opened = await browser_open({"url": url}, agent_id="a1", session_id="s1", run_id="cap-run")
        assert "Count" in opened["observation"]

        # find the button ref from the observation text
        line = next(x for x in opened["observation"].splitlines() if "Count" in x)
        ref = line.split()[0]
        acted = await browser_act(
            {"action": "click", "target": ref},
            agent_id="a1",
            session_id="s1",
            run_id="cap-run",
        )
        assert "Count: 1" in acted["delta"]

        closed = await browser_close({}, agent_id="a1", session_id="s1", run_id="cap-run")
        assert closed == {"closed": True}
    finally:
        from agentos.browser.registry import browser_registry

        await browser_registry.close_for_run("cap-run")
        httpd.shutdown()
