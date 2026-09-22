"""Raw-CDP browser session — the Browser module's protocol core.

Promoted from scripts/spike_browser/adapters.py, hardened for production:
one browser process + one websocket + one page per session, event-driven
waits, role-filtered AX projection with a hard element cap, delta-by-line
post-action observations. See the module docstring for the budget context.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# Interactive + landmark roles only — spike-validated: structural roles
# (row/cell/listitem) blew HN's observation to 3853 tokens; this projection
# brings it to ~700. Structural detail is reachable via extract/scoped
# observe, not the default observation.
KEEP_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "heading",
    "navigation",
    "main",
    "img",
    "status",
}
MAX_ELEMENTS = 80
LOAD_TIMEOUT_S = 30.0
CMD_TIMEOUT_S = 15.0

# Research mode — heavy non-content resources blocked to cut load time and
# bandwidth. URL glob patterns for Network.setBlockedURLs.
RESEARCH_BLOCKLIST = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.avif",
    "*.ico",
    "*.svg",
    "*.mp4",
    "*.webm",
    "*.mov",
    "*.mp3",
    "*.wav",
    "*.ogg",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.eot",
    "*google-analytics*",
    "*googletagmanager*",
    "*doubleclick*",
    "*facebook.net*",
    "*hotjar*",
    "*segment.io*",
]


@dataclass
class Element:
    ref: str
    role: str
    name: str
    value: str | None = None

    def line(self) -> str:
        v = f' value="{self.value}"' if self.value else ""
        return f"{self.ref} {self.role} {self.name!r}{v}"


@dataclass
class Observation:
    url: str
    title: str
    elements: list[Element] = field(default_factory=list)

    def serialize(self) -> str:
        lines = [f"url: {self.url}", f"title: {self.title}"]
        lines += [e.line() for e in self.elements]
        return "\n".join(lines)

    def delta(self, prev: Observation) -> str:
        old = {e.ref: e.line() for e in prev.elements}
        new = {e.ref: e.line() for e in self.elements}
        out = []
        if self.url != prev.url:
            out.append(f"url: {prev.url} -> {self.url}")
        if self.title != prev.title:
            out.append(f"title: {prev.title} -> {self.title}")
        for ref, line in new.items():
            if ref not in old:
                out.append(f"+ {line}")
            elif old[ref] != line:
                out.append(f"~ {line}")
        for ref in old:
            if ref not in new:
                out.append(f"- {old[ref]}")
        return "\n".join(out) or "(no change)"


class BrowserError(Exception):
    """Honest failure surface — callers report this, never swallow."""


class BrowserSession:
    """One Chromium process + one page, driven over one CDP websocket."""

    def __init__(self, binary: Path, profile_dir: Path, staging_dir: Path | None = None) -> None:
        self._binary = binary
        self._profile_dir = profile_dir
        self._staging_dir = staging_dir
        self._proc: subprocess.Popen | None = None
        self._ws = None
        self._session: str | None = None
        self._msg_id = 0
        self._pending: list[dict] = []
        self._last_obs: Observation | None = None
        self._research = False
        self.fell_back = False
        self.downloads: list[dict] = []
        self._download_guids: dict[str, str] = {}
        self.last_activity = time.monotonic()

    # -- lifecycle ----------------------------------------------------------

    async def open(self, url: str, research: bool = False) -> Observation:
        import websockets

        self._proc = subprocess.Popen(
            [
                str(self._binary),
                "--headless=new",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._profile_dir}",
                "--no-first-run",
                "--disable-extensions",
                "--mute-audio",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port_file = self._profile_dir / "DevToolsActivePort"
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while not port_file.exists():
            if self._proc.poll() is not None:
                raise BrowserError("browser process exited during startup")
            if time.monotonic() > deadline:
                raise BrowserError("browser did not expose a debug port")
            await asyncio.sleep(0.05)
        port, ws_path = port_file.read_text().splitlines()[:2]
        self._ws = await websockets.connect(
            f"ws://127.0.0.1:{port}{ws_path}", max_size=64 * 1024 * 1024
        )
        target = await self._send("Target.createTarget", {"url": "about:blank"}, session=False)
        attached = await self._send(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": True},
            session=False,
        )
        self._session = attached["sessionId"]
        await self._send("Page.enable")
        await self._send("Runtime.enable")
        if self._staging_dir:
            # Plan: downloads enter run staging and never execute automatically.
            self._staging_dir.mkdir(parents=True, exist_ok=True)
            await self._send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(self._staging_dir),
                    "eventsEnabled": True,
                },
                session=False,
            )
        self._research = research
        if research:
            await self._send("Network.enable")
            await self._send("Network.setBlockedURLs", {"urls": RESEARCH_BLOCKLIST})
        try:
            await self.navigate(url)
        except BrowserError:
            if not research:
                raise
            # Plan-mandated normal-load fallback — some sites break when
            # media/fonts are blocked. Degrade honestly rather than fail.
            self._research = False
            self.fell_back = True
            await self._send("Network.setBlockedURLs", {"urls": []})
            await self.navigate(url)
        return await self.observe()

    async def navigate(self, url: str) -> None:
        await self._send("Page.navigate", {"url": url})
        await self._wait_load()

    async def close(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- protocol -----------------------------------------------------------

    async def _send(self, method: str, params: dict | None = None, session: bool = True) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        msg: dict = {"id": mid, "method": method, "params": params or {}}
        if session and self._session:
            msg["sessionId"] = self._session
        await self._ws.send(json.dumps(msg))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=CMD_TIMEOUT_S)
            data = json.loads(raw)
            if data.get("id") == mid:
                if "error" in data:
                    raise BrowserError(f"{method}: {data['error'].get('message', data['error'])}")
                return data.get("result", {})
            self._pending.append(data)

    async def _wait_load(self) -> None:
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            for i, ev in enumerate(self._pending):
                if ev.get("method") == "Page.loadEventFired":
                    self._pending.pop(i)
                    return
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=0.5)
                self._pending.append(json.loads(raw))
            except TimeoutError:
                if not self.alive():
                    raise BrowserError("browser exited while loading") from None
        raise BrowserError("page load timed out")

    def _drain_events(self) -> None:
        """Consume queued browser-level events (downloads) into state."""
        keep = []
        for ev in self._pending:
            method = ev.get("method")
            params = ev.get("params", {})
            if method == "Browser.downloadWillBegin":
                self._download_guids[params["guid"]] = params.get("suggestedFilename", "download")
            elif method == "Browser.downloadProgress" and params.get("state") == "completed":
                name = self._download_guids.pop(params["guid"], "download")
                self.downloads.append({"filename": name, "state": "completed"})
            elif method == "Browser.downloadProgress" and params.get("state") == "canceled":
                self._download_guids.pop(params["guid"], None)
            else:
                keep.append(ev)
        self._pending = keep

    # -- module verbs --------------------------------------------------------

    async def observe(self, scope: str | None = None) -> Observation:
        self.last_activity = time.monotonic()
        tree = await self._send("Accessibility.getFullAXTree")
        self._drain_events()
        doc = await self._send(
            "Runtime.evaluate", {"expression": "location.href + '|' + document.title"}
        )
        url, _, title = doc["result"]["value"].partition("|")
        nodes = tree.get("nodes", [])

        scope_ids: set[str] | None = None
        if scope:
            backend_id = await self._resolve_scope(scope)
            by_id = {n["nodeId"]: n for n in nodes}
            root = next((n for n in nodes if n.get("backendDOMNodeId") == backend_id), None)
            if root is None:
                raise BrowserError(f"scope not in accessibility tree: {scope}")
            # AX subtree walk — project every non-ignored role inside the
            # region (scoped observe exists to reach role-filtered content
            # like table rows; the element cap still applies).
            scope_ids = set()
            stack = [root["nodeId"]]
            while stack:
                nid = stack.pop()
                if nid in scope_ids or nid not in by_id:
                    continue
                scope_ids.add(nid)
                stack.extend(by_id[nid].get("childIds") or [])

        elements: list[Element] = []
        omitted = 0
        for node in nodes:
            if node.get("ignored"):
                continue
            if scope_ids is not None:
                if node["nodeId"] not in scope_ids:
                    continue
            elif (node.get("role") or {}).get("value", "") not in KEEP_ROLES:
                continue
            role = (node.get("role") or {}).get("value", "")
            name = (node.get("name") or {}).get("value", "")
            value = (node.get("value") or {}).get("value")
            ref = f"e{node.get('backendDOMNodeId') or node['nodeId']}"
            if len(elements) >= MAX_ELEMENTS:
                omitted += 1
                continue
            elements.append(
                Element(ref=ref, role=role, name=name, value=str(value) if value else None)
            )
        if omitted:
            elements.append(
                Element(
                    ref="-",
                    role="note",
                    name=f"{omitted} elements omitted — call browser_observe(scope=…) to inspect",
                )
            )
        obs = Observation(url=url, title=title, elements=elements)
        self._last_obs = obs
        return obs

    async def _resolve_scope(self, scope: str) -> int:
        """Scope string → backendDOMNodeId. Accepts an element ref (`e123`)
        or a CSS selector resolved against the live DOM."""
        if scope.startswith("e") and scope[1:].isdigit():
            return int(scope[1:])
        root = await self._send("DOM.getDocument", {"depth": 0})
        hit = await self._send(
            "DOM.querySelector",
            {"nodeId": root["root"]["nodeId"], "selector": scope},
        )
        if not hit.get("nodeId"):
            raise BrowserError(f"scope matched nothing: {scope}")
        described = await self._send("DOM.describeNode", {"nodeId": hit["nodeId"]})
        return described["node"]["backendNodeId"]

    async def act(self, action: str, ref: str, value: str | None = None) -> str:
        self.last_activity = time.monotonic()
        backend_id = int(ref[1:])
        node = await self._send("DOM.resolveNode", {"backendNodeId": backend_id})
        oid = node["object"]["objectId"]
        if action == "click":
            await self._send(
                "Runtime.callFunctionOn",
                {"objectId": oid, "functionDeclaration": "function(){this.click()}"},
            )
        elif action == "type":
            await self._send(
                "Runtime.callFunctionOn",
                {
                    "objectId": oid,
                    "functionDeclaration": (
                        "function(v){this.focus();this.value=v;"
                        "this.dispatchEvent(new Event('input',{bubbles:true}))}"
                    ),
                    "arguments": [{"value": value}],
                },
            )
        elif action == "navigate":
            if not value:
                raise BrowserError("navigate requires a url value")
            await self.navigate(value)
        else:
            raise BrowserError(f"unknown action: {action}")
        prev = self._last_obs
        obs = await self.observe()
        delta = obs.delta(prev) if prev else obs.serialize()
        if self.downloads:
            names = ", ".join(d["filename"] for d in self.downloads)
            delta += f"\n(downloads staged: {names} — in workspace downloads/, never executed)"
        return delta

    async def extract(self, expression: str) -> str:
        """Run a JS expression and return its JSON-serialized value."""
        self.last_activity = time.monotonic()
        res = await self._send(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        if "exceptionDetails" in res:
            raise BrowserError("extract expression threw")
        return json.dumps(res["result"].get("value"))

    async def screenshot(self) -> bytes:
        """On-demand visual observation — PNG bytes of the current viewport.
        Callers persist it as a traceable file; pixels never ride tool output."""
        self.last_activity = time.monotonic()
        res = await self._send("Page.captureScreenshot", {"format": "png"})
        import base64

        return base64.b64decode(res["data"])
