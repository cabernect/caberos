"""W4 Browser module — CDP session + capabilities.

Live tests launch the real managed runtime against a local dynamic page and
are skipped when no Chromium binary is discoverable (CI without a browser).
Unit tests cover the observation machinery and honest error paths without a
browser.
"""

import asyncio
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


@needs_browser
async def test_live_visual_observe_saves_artifact(tmp_path):
    """visual=True stores a PNG under artifacts/ and attaches image content
    for vision models only."""
    httpd, url = _serve(tmp_path / "srv")
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        await browser_open({"url": url}, agent_id="a1", session_id="s1", run_id="vis-run")
        out = await browser_observe(
            {"visual": True},
            agent_id="a1",
            session_id="s1",
            run_id="vis-run",
            workspace_path=str(ws),
            supports_vision=True,
        )
        shot = ws / out["screenshot"]
        assert shot.exists() and shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert out["screenshot"].startswith("artifacts/browser/")
        assert out["_model_content"][1]["type"] == "image_url"

        out2 = await browser_observe(
            {"visual": True},
            agent_id="a1",
            session_id="s1",
            run_id="vis-run",
            workspace_path=str(ws),
            supports_vision=False,
        )
        assert "_model_content" not in out2
        assert "lacks vision" in out2["note"]
    finally:
        from agentos.browser.registry import browser_registry

        await browser_registry.close_for_run("vis-run")
        httpd.shutdown()


# --- runtime discovery/install --------------------------------------------


def test_platform_key_maps_this_machine():
    import platform as _platform
    import sys

    from agentos.browser import runtime

    key = runtime._platform_key()
    if sys.platform == "darwin":
        expected = "mac-arm64" if _platform.machine() == "arm64" else "mac-x64"
        assert key == expected
    else:
        assert key in ("linux64", "win64", "win32", None)


def test_runtime_status_reports_state(monkeypatch, tmp_path):
    from agentos.browser import runtime

    monkeypatch.delenv("AGENTOS_BROWSER_BINARY", raising=False)
    from agentos.config import settings

    monkeypatch.setattr(settings, "browser_binary", "")
    monkeypatch.setattr(runtime, "_playwright_cache_roots", lambda: [])
    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path / "brt")
    status = runtime.runtime_status()
    assert status["status"] == "runtime_unavailable"
    assert status["installable"] is True


async def test_install_runtime_fetches_extracts_and_healthchecks(monkeypatch, tmp_path):
    """The installer path end to end — network faked with a real zip built
    in-memory, signature/health checks stubbed at the platform boundary."""
    import zipfile as zf

    from agentos.browser import runtime

    plat = runtime._platform_key()
    inner = {
        "mac-arm64": "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "mac-x64": "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "linux64": "chrome-linux64/chrome",
        "win64": "chrome-win64/chrome.exe",
        "win32": "chrome-win32/chrome.exe",
    }[plat]

    zip_path = tmp_path / "chrome.zip"
    with zf.ZipFile(zip_path, "w") as z:
        z.writestr(inner, b"#!/bin/sh\necho 'Google Chrome for Testing 145.0.7632.6'\n")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "versions": [
                    {
                        "version": runtime.RUNTIME_VERSION,
                        "downloads": {"chrome": [{"platform": plat, "url": "https://x/zip"}]},
                    }
                ]
            }

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path / "brt")
    monkeypatch.setitem(__import__("sys").modules, "httpx", type("m", (), {"AsyncClient": _Client}))

    async def fake_download(url, dest):
        dest.write_bytes(zip_path.read_bytes())
        return "deadbeef"

    monkeypatch.setattr(runtime, "_download", fake_download)
    monkeypatch.setattr(runtime, "_verify_signature", lambda b, p: "signature: stubbed")
    monkeypatch.setattr(
        runtime, "_health_check", lambda b: "Google Chrome for Testing 145.0.7632.6"
    )

    out = await runtime.install_runtime()
    assert out["status"] == "installed"
    assert Path(out["binary"]).exists()
    assert "sha256" in out and out["signature"] == "signature: stubbed"
    # and the managed install is now discoverable (no binary override set)
    monkeypatch.delenv("AGENTOS_BROWSER_BINARY", raising=False)
    from agentos.config import settings

    monkeypatch.setattr(settings, "browser_binary", "")
    monkeypatch.setattr(runtime, "_playwright_cache_roots", lambda: [])
    assert runtime.find_browser_binary() == Path(out["binary"])

    # remove
    assert runtime.remove_runtime()["status"] == "removed"
    assert not (tmp_path / "brt" / runtime.RUNTIME_VERSION).exists()


async def test_install_runtime_unsupported_platform(monkeypatch):
    from agentos.browser import runtime

    monkeypatch.setattr(runtime, "_platform_key", lambda: None)
    out = await runtime.install_runtime()
    assert out["status"] == "unsupported_platform"


SCOPED_PAGE = """<!DOCTYPE html><html><head><title>scoped</title></head><body>
<main><h1>Report</h1><button id="go">Go</button>
<ul id="items"><li>alpha</li><li>beta</li><li>gamma</li></ul></main>
</body></html>"""


@needs_browser
async def test_scoped_observe_reaches_role_filtered_content(tmp_path):
    """Default obs drops listitems; scope (CSS or landmark ref) reveals them."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text(SCOPED_PAGE)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    session = BrowserSession(_browser, tmp_path / "profile")
    try:
        obs = await session.open(url)
        # default projection: no listitem role survives
        assert not any(e.role == "listitem" for e in obs.elements)

        # scope by CSS selector into the list
        scoped = await session.observe(scope="#items")
        names = {e.name for e in scoped.elements}
        assert {"alpha", "beta", "gamma"} <= names

        # scope by a visible landmark ref (main) — same content reachable
        main_ref = next(e.ref for e in obs.elements if e.role == "main")
        scoped2 = await session.observe(scope=main_ref)
        names2 = {e.name for e in scoped2.elements}
        assert {"alpha", "beta", "gamma"} <= names2

        # bad scope errors honestly
        with pytest.raises(BrowserError, match="matched nothing"):
            await session.observe(scope="#nope")
    finally:
        await session.close()
        httpd.shutdown()


@needs_browser
async def test_research_mode_blocks_media(tmp_path):
    """research mode must actually block — verify via a real image fetch."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text('<html><body><h1>t</h1><img id="im" src="x.png"></body></html>')
    # a real decodable 1x1 PNG so naturalWidth distinguishes load-vs-block
    import base64 as _b64

    (srv / "x.png").write_bytes(
        _b64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    async def img_width(research: bool) -> str:
        session = BrowserSession(_browser, tmp_path / f"p{research}")
        try:
            await session.open(url, research=research)
            await asyncio.sleep(0.3)  # let the img attempt resolve
            return await session.extract("document.getElementById('im').naturalWidth")
        finally:
            await session.close()

    try:
        assert json.loads(await img_width(False)) > 0  # normal load: image loads
        assert json.loads(await img_width(True)) == 0  # research: blocked
    finally:
        httpd.shutdown()


@needs_browser
async def test_download_lands_in_staging(tmp_path):
    """Click a download link → file staged under workspace downloads/,
    surfaced in the post-action delta, never executed."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text(
        '<html><body><a href="data.csv" download="report.csv">Get data</a></body></html>'
    )
    (srv / "data.csv").write_text("a,b\n1,2\n")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    staging = tmp_path / "downloads"
    session = BrowserSession(_browser, tmp_path / "profile", staging_dir=staging)
    try:
        obs = await session.open(url)
        link = next(e for e in obs.elements if e.role == "link")
        await session.act("click", link.ref)
        await asyncio.sleep(1.0)  # download events arrive async
        await session.observe()  # drains the event queue
        assert (staging / "report.csv").read_text() == "a,b\n1,2\n"
        assert session.downloads[0]["filename"] == "report.csv"
    finally:
        await session.close()
        httpd.shutdown()


# --- profiles: domain scope + lock -----------------------------------------


def test_url_in_scope_subdomain_rules():
    from agentos.browser.registry import _url_in_scope

    domains = ["tradingview.com"]
    assert _url_in_scope("https://tradingview.com/chart", domains)
    assert _url_in_scope("https://www.tradingview.com/", domains)
    assert not _url_in_scope("https://eviltradingview.com/", domains)
    assert not _url_in_scope("https://example.com/", domains)


@needs_browser
async def test_domain_scope_blocks_out_of_scope_navigation(tmp_path):
    """Fetch interception must fail a Document request to an out-of-scope
    domain and record it — not silently follow."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text("<html><body><h1>in scope</h1></body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    session = BrowserSession(_browser, tmp_path / "profile")
    try:
        await session.open(url, allowed_domains=["127.0.0.1"])
        assert session.blocked_navigations == []
        # in-scope navigate continues normally
        await session.navigate(url)
        # out-of-scope navigate is failed by interception
        try:
            await session.navigate("https://example.com/")
        except BrowserError:
            pass  # load may not fire on a failed request — either way it must be recorded
        await asyncio.sleep(0.5)
        await session.observe()
        assert any("example.com" in u for u in session.blocked_navigations)
    finally:
        await session.close()
        httpd.shutdown()


@needs_browser
async def test_profile_lock_refuses_second_run(tmp_path, monkeypatch):
    """A named profile held by one run must refuse a second run honestly."""
    from agentos.browser import registry as reg_mod
    from agentos.browser.registry import BrowserRegistry

    monkeypatch.setattr(reg_mod, "_profiles_root", lambda: tmp_path / "profiles")
    httpd, url = _serve(tmp_path / "srv")
    reg = BrowserRegistry()
    try:
        await reg.get_or_open(
            url,
            agent_id="a",
            session_id="s",
            run_id="r1",
            profile="locked",
            allowed_domains=None,
        )
        with pytest.raises(BrowserError, match="in use by another run"):
            await reg.get_or_open(
                url,
                agent_id="a",
                session_id="s",
                run_id="r2",
                profile="locked",
                allowed_domains=None,
            )
        # and the profile dir persists after close (not a temp dir)
        assert (tmp_path / "profiles" / "locked").exists()
    finally:
        await reg.shutdown_all()
        httpd.shutdown()


@needs_browser
async def test_scroll_moves_viewport_and_reveals(tmp_path):
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    # tall page — content below the fold
    (srv / "index.html").write_text(
        '<html><body style="margin:0"><div style="height:3000px">top</div>'
        '<button id="b">Bottom</button></body></html>'
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    session = BrowserSession(_browser, tmp_path / "profile")
    try:
        await session.open(url)
        assert json.loads(await session.extract("window.scrollY")) == 0
        await session.act("scroll", "", "down")
        assert json.loads(await session.extract("window.scrollY")) > 0
        # scroll the button into view by ref
        obs = await session.observe()
        btn = next(e for e in obs.elements if e.role == "button")
        await session.act("scroll", btn.ref)
        top = json.loads(
            await session.extract("document.getElementById('b').getBoundingClientRect().top")
        )
        assert 0 <= top < 800  # inside the viewport
    finally:
        await session.close()
        httpd.shutdown()


@needs_browser
async def test_large_extract_stages_to_workspace(tmp_path):
    """>20k extract lands as a workspace artifact + bounded preview."""
    from agentos.browser.registry import browser_registry
    from agentos.capabilities.tools.browser import browser_extract

    httpd, url = _serve(tmp_path / "srv")
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        await browser_open(
            {"url": url},
            agent_id="a",
            session_id="s",
            run_id="ext-run",
            workspace_path=str(ws),
        )
        out = await browser_extract(
            {"expression": "Array(5000).fill('row-data-here').join(',')"},
            agent_id="a",
            run_id="ext-run",
            workspace_path=str(ws),
        )
        assert out["staged"].startswith("artifacts/browser/extract-")
        assert len(out["preview"]) == 20_000
        staged = ws / out["staged"]
        assert staged.exists() and len(staged.read_text()) > 20_000
    finally:
        await browser_registry.close_for_run("ext-run")
        httpd.shutdown()


@needs_browser
async def test_visible_session_survives_idle_reaper(tmp_path, monkeypatch):
    """A windowed session exists for human takeover — the 120s reaper must
    not kill it mid-MFA. Headless sessions still reap."""
    from agentos.browser import registry as reg_mod
    from agentos.browser.registry import BrowserRegistry

    monkeypatch.setattr(reg_mod, "IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(reg_mod, "REAP_INTERVAL_S", 0.05)
    httpd, url = _serve(tmp_path / "srv")
    reg = BrowserRegistry()
    try:
        await reg.get_or_open(url, agent_id="a", session_id="s", run_id="vis")
        # mark it visible post-hoc (same flag the real open path sets)
        reg._sessions["vis"].visible = True
        await reg.get_or_open(url, agent_id="a", session_id="s", run_id="head")
        await asyncio.sleep(0.6)  # several reap ticks past the timeout
        assert "head" not in reg._sessions  # headless reaped
        assert "vis" in reg._sessions  # visible survived
        assert reg._sessions["vis"].session.alive()
    finally:
        await reg.shutdown_all()
        httpd.shutdown()


@needs_browser
async def test_form_actions_select_keypress_hover(tmp_path):
    """select picks an option, keypress submits a form, hover reveals content."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text("""<html><body>
<select id="s" aria-label="choice" onchange="document.getElementById('out').textContent=this.value">
  <option value="">pick</option><option value="b">bee</option></select>
<div id="out"></div>
<form id="f" onsubmit="document.getElementById('sub').textContent='yes';return false">
  <input id="q" aria-label="q"></form>
<div id="sub"></div>
<div id="hov" onmouseover="document.getElementById('hid').textContent='shown'">hover me</div>
<div id="hid"></div>
</body></html>""")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    session = BrowserSession(_browser, tmp_path / "profile")
    try:
        obs = await session.open(url)
        sel = next(e for e in obs.elements if e.role == "combobox")
        inp = next(e for e in obs.elements if e.role == "textbox")

        await session.act("select", sel.ref, "b")
        assert "b" in await session.extract("document.getElementById('out').textContent")

        await session.act("type", inp.ref, "hello")
        await session.act("keypress", inp.ref, "Enter")
        assert "yes" in await session.extract("document.getElementById('sub').textContent")

        # hover target isn't a KEEP role — reach it via a CSS-scoped observe
        obs2 = await session.observe(scope="#hov")
        hov_ref = next(e for e in obs2.elements if "hover me" in e.name)
        await session.act("hover", hov_ref.ref)
        await asyncio.sleep(0.2)
        assert "shown" in await session.extract("document.getElementById('hid').textContent")
    finally:
        await session.close()
        httpd.shutdown()


def test_launch_args_container_flags(monkeypatch, tmp_path):
    """Container flag adds the launch-fatal-in-Docker trio; headless default."""
    from agentos.browser.cdp import BrowserSession

    s = BrowserSession(tmp_path / "bin", tmp_path / "prof")
    monkeypatch.delenv("AGENTOS_BROWSER_NO_SANDBOX", raising=False)
    args = s._launch_args(visible=False)
    assert "--headless=new" in args
    assert "--no-sandbox" not in args
    monkeypatch.setenv("AGENTOS_BROWSER_NO_SANDBOX", "1")
    args = s._launch_args(visible=False)
    for flag in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        assert flag in args
    # visible drops headless
    assert "--headless=new" not in s._launch_args(visible=True)


@needs_browser
async def test_live_iframe_and_shadow_dom(tmp_path):
    """Scoped observe reaches into iframes (frame AX tree via contentDocument)
    and shadow DOM (flattened by a11y); cross-origin frames are observable
    and actionable through browser-side a11y + backendNodeId routing."""
    import http.server

    inner = (
        "<button id='in' onclick=\"document.body.dataset.hit='yes';"
        "this.textContent='CLICKED-IN-XO'\">Frame button</button>"
        "<a href='#'>Frame link</a>"
    )
    outer = """<html><body><main>
<button id="top">Top</button>
<div id="sh"></div>
<iframe id="f" src="/inner"></iframe>
<iframe id="xf" src="http://127.0.0.1:{XPORT}/inner"></iframe>
<script>
document.getElementById('sh').attachShadow({mode:'open'}).innerHTML =
  '<button>Shadow button</button>';
</script>
</main></body></html>"""

    class Inner(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = inner.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    # second server = different port = different origin for the cross-origin frame
    xsrv = http.server.HTTPServer(("127.0.0.1", 0), Inner)
    threading.Thread(target=xsrv.serve_forever, daemon=True).start()
    page = outer.replace("{XPORT}", str(xsrv.server_port))

    class Outer(Inner):
        def do_GET(self):
            body = inner.encode() if self.path == "/inner" else page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Outer)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/"

    session = BrowserSession(_browser, tmp_path / "prof")
    (tmp_path / "prof").mkdir()
    try:
        obs = await session.open(url)
        await asyncio.sleep(0.5)
        names = [e.name for e in obs.elements]
        assert "Shadow button" in names
        assert any(e.role == "Iframe" for e in obs.elements)

        # scope into the same-origin frame → its AX subtree is projected
        frame_obs = await session.observe(scope="#f")
        btn = next(e for e in frame_obs.elements if e.name == "Frame button")
        assert any(e.name == "Frame link" for e in frame_obs.elements)

        # refs inside the frame resolve and act
        await session.act("click", btn.ref)
        assert "yes" in await session.extract(
            "document.querySelector('#f').contentDocument.body.dataset.hit"
        )

        # cross-origin frame (different port = different origin) → fully
        # observable and actionable via browser-side a11y + backendNodeId
        xo_obs = await session.observe(scope="#xf")
        xo_btn = next(e for e in xo_obs.elements if e.name == "Frame button")
        await session.act("click", xo_btn.ref)
        xo_after = await session.observe(scope="#xf")
        assert any(e.name == "CLICKED-IN-XO" for e in xo_after.elements)
    finally:
        await session.close()
        httpd.shutdown()
        xsrv.shutdown()


@needs_browser
async def test_live_browser_crash_fails_honestly(tmp_path):
    """Killing the browser process mid-session → subsequent calls fail with a
    clear BrowserError, and close() stays safe."""
    httpd, url = _serve(tmp_path)
    session = BrowserSession(_browser, tmp_path / "prof")
    (tmp_path / "prof").mkdir()
    try:
        await session.open(url)
        session._proc.kill()
        await asyncio.sleep(0.3)
        with pytest.raises(BrowserError, match="not running|connection lost"):
            await session.observe()
        await session.close()  # must not raise on a dead session
    finally:
        httpd.shutdown()


@needs_browser
async def test_domain_redirect_pause_and_widen(tmp_path):
    """Out-of-scope navigation is blocked + recorded; the operator-approved
    retry (allow_domain) widens the session scope and the nav proceeds."""
    srv = tmp_path / "srv"
    srv.mkdir(parents=True)
    (srv / "index.html").write_text("<html><body><h1>in scope</h1></body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"

    session = BrowserSession(_browser, tmp_path / "profile")
    try:
        await session.open(url, allowed_domains=["127.0.0.1"])
        # out-of-scope host (localhost ≠ 127.0.0.1 as a hostname) is blocked
        blocked_url = f"http://localhost:{httpd.server_port}/index.html"
        try:
            await session.navigate(blocked_url)
        except BrowserError:
            pass
        await asyncio.sleep(0.5)
        await session.observe()
        assert any("localhost" in u for u in session.blocked_navigations)

        # operator approves widening — the retry proceeds
        session.allow_domain_for(blocked_url)
        await session.navigate(blocked_url)
        obs = await session.observe()
        assert "localhost" in obs.url
    finally:
        await session.close()
        httpd.shutdown()


async def test_browser_open_visible_refused_on_scheduled_run():
    """Heartbeat/scheduled runs must never pop a surprise window (plan:
    'scheduled work never opens surprise windows')."""
    result = await browser_open(
        {"url": "http://x", "visible": True},
        agent_id="a",
        run_id="r",
        trigger="heartbeat",
    )
    assert result["status"] == "visible_refused"
