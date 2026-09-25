"""Raw-CDP browser session — the Browser module's protocol core.

Promoted from scripts/spike_browser/adapters.py, hardened for production:
one browser process + one websocket + one page per session, event-driven
waits, role-filtered AX projection with a hard element cap, delta-by-line
post-action observations. See the module docstring for the budget context.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

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
    "Iframe",
}
MAX_ELEMENTS = 80
LOAD_TIMEOUT_S = 30.0
CMD_TIMEOUT_S = 15.0


def _display_available() -> bool:
    """Visible mode needs a real display — headed Chrome on a displayless
    Linux host exits at startup with a cryptic error. Check first."""
    import sys

    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True  # macOS/Windows sessions always have a window server


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

# windowsVirtualKeyCode for named keys — form submission and focus movement
# key off the vk code, not just the key name.
_KEY_CODES = {
    "Enter": 13,
    "Tab": 9,
    "Escape": 27,
    "Backspace": 8,
    "Delete": 46,
    "ArrowUp": 38,
    "ArrowDown": 40,
    "ArrowLeft": 37,
    "ArrowRight": 39,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
    " ": 32,
}

# Named keys that produce a char event — Enter/space. This is what triggers
# form submission; a raw down/up alone doesn't.
_KEY_TEXT = {"Enter": "\r", " ": " "}


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
        self._waiters: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._pending: list[dict] = []
        self._event_flag = asyncio.Event()
        self._fetch_queue: asyncio.Queue | None = None
        self._intercept_task: asyncio.Task | None = None
        self._allowed_domains: set[str] | None = None
        self.blocked_navigations: list[str] = []
        self._last_obs: Observation | None = None
        self._research = False
        self.fell_back = False
        self.downloads: list[dict] = []
        self._download_guids: dict[str, str] = {}
        self.last_activity = time.monotonic()

    # -- lifecycle ----------------------------------------------------------

    def _launch_args(self, visible: bool) -> list[str]:
        args = [
            str(self._binary),
            "--remote-debugging-port=0",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--mute-audio",
            "about:blank",
        ]
        if not visible:
            args.insert(1, "--headless=new")
        # Containers can't run Chrome's sandbox (no userns/CAP_SYS_ADMIN) and
        # /dev/shm is tiny — both are launch-fatal without these flags.
        if os.environ.get("AGENTOS_BROWSER_NO_SANDBOX"):
            args += ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        return args

    async def open(
        self,
        url: str,
        research: bool = False,
        allowed_domains: list[str] | None = None,
        visible: bool = False,
    ) -> Observation:
        import websockets

        if visible and not _display_available():
            raise BrowserError(
                "visible mode needs a desktop session — this host has no "
                "display (use headless on web/Docker deployments)"
            )

        port_file = self._profile_dir / "DevToolsActivePort"
        # Persistent profiles carry a stale port file from the last launch —
        # drop it before spawning so we wait on the new process's port.
        port_file.unlink(missing_ok=True)
        self._proc = subprocess.Popen(
            self._launch_args(visible),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
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
        self._reader_task = asyncio.create_task(self._reader_loop())
        # Chrome opens with an about:blank tab — attach to THAT target
        # instead of creating a second tab we'd just orphan.
        targets = await self._send("Target.getTargets", session=False)
        page = next(
            (t for t in targets["targetInfos"] if t.get("type") == "page"),
            None,
        )
        if page is None:
            target = await self._send("Target.createTarget", {"url": "about:blank"}, session=False)
            page = {"targetId": target["targetId"]}
        attached = await self._send(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True},
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
        if allowed_domains:
            # Arm interception before the first navigation — a redirect
            # chain during initial load must not escape the profile scope.
            await self.set_domain_scope(allowed_domains)
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
        for task in (self._intercept_task, self._reader_task):
            if task and not task.done():
                task.cancel()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- protocol -----------------------------------------------------------
    # One reader task owns the socket: command responses resolve keyed
    # futures, events land in _pending (or the interception queue). This is
    # what lets the interception loop answer Fetch.requestPaused while a
    # navigate command is in flight — a request/response pump can't.

    async def _reader_loop(self) -> None:
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                if "id" in data:
                    fut = self._waiters.pop(data["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(data)
                elif self._fetch_queue is not None and data.get("method") == "Fetch.requestPaused":
                    await self._fetch_queue.put(data)
                else:
                    self._pending.append(data)
                    self._event_flag.set()
        except Exception:
            pass
        finally:
            for fut in self._waiters.values():
                if not fut.done():
                    fut.set_exception(BrowserError("browser connection lost"))
            self._waiters.clear()
            self._event_flag.set()

    async def _send(self, method: str, params: dict | None = None, session: bool = True) -> dict:
        if not self.alive():
            raise BrowserError("browser is not running")
        self._msg_id += 1
        mid = self._msg_id
        fut = asyncio.get_running_loop().create_future()
        self._waiters[mid] = fut
        msg: dict = {"id": mid, "method": method, "params": params or {}}
        if session and self._session:
            msg["sessionId"] = self._session
        try:
            await self._ws.send(json.dumps(msg))
            data = await asyncio.wait_for(fut, timeout=CMD_TIMEOUT_S)
        except TimeoutError:
            self._waiters.pop(mid, None)
            raise BrowserError(f"{method}: timed out") from None
        if "error" in data:
            raise BrowserError(f"{method}: {data['error'].get('message', data['error'])}")
        return data.get("result", {})

    async def _wait_load(self) -> None:
        # Prefer the full load event; DOMContentLoaded + a short settle is the
        # fallback so slow third-party resources don't stall every navigation
        # (e.g. analytics beacons keeping `load` pending for 15s+).
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        dom_ready_at: float | None = None
        while time.monotonic() < deadline:
            for i, ev in enumerate(self._pending):
                method = ev.get("method")
                if method == "Page.loadEventFired":
                    self._pending.pop(i)
                    return
                if method == "Page.domContentEventFired":
                    self._pending.pop(i)
                    dom_ready_at = dom_ready_at or time.monotonic()
            if dom_ready_at and time.monotonic() - dom_ready_at >= 1.5:
                return
            self._event_flag.clear()
            try:
                await asyncio.wait_for(self._event_flag.wait(), timeout=0.5)
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

    # -- domain scoping -------------------------------------------------------
    # Persistent profiles declare allowed domains; every Document request is
    # paused at Request stage and either continued or failed. Blocked targets
    # are recorded so observations can report them honestly.

    async def set_domain_scope(self, domains: list[str]) -> None:
        self._allowed_domains = {d.lower().lstrip("*.") for d in domains}
        self._fetch_queue = asyncio.Queue()
        await self._send(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*",
                        "requestStage": "Request",
                        "resourceType": "Document",
                    }
                ]
            },
        )
        self._intercept_task = asyncio.create_task(self._intercept_loop())

    def domain_allowed(self, url: str) -> bool:
        if self._allowed_domains is None:
            return True
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self._allowed_domains)

    def allow_domain_for(self, url: str) -> None:
        """Widen this session's domain scope to the given URL's host. Only
        reachable through an approval-gated act call — the approval prompt
        is the operator's decision point ('domain redirect pause')."""
        if self._allowed_domains is not None:
            host = (urlparse(url).hostname or "").lower()
            if host:
                self._allowed_domains.add(host)

    async def _intercept_loop(self) -> None:
        while True:
            ev = await self._fetch_queue.get()
            params = ev.get("params", {})
            rid = params.get("requestId")
            url = params.get("request", {}).get("url", "")
            try:
                if self.domain_allowed(url):
                    await self._send("Fetch.continueRequest", {"requestId": rid})
                else:
                    self.blocked_navigations.append(url)
                    await self._send(
                        "Fetch.failRequest",
                        {"requestId": rid, "errorReason": "BlockedByClient"},
                    )
            except Exception:
                pass  # browser gone mid-intercept — shutdown handles it

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

        if scope:
            nodes = await self._scoped_nodes(scope, nodes)

        elements: list[Element] = []
        omitted = 0
        for node in nodes:
            if node.get("ignored"):
                continue
            if scope is None and (node.get("role") or {}).get("value", "") not in KEEP_ROLES:
                continue
            role = (node.get("role") or {}).get("value", "")
            name = (node.get("name") or {}).get("value", "")
            value = (node.get("value") or {}).get("value")
            backend = node.get("backendDOMNodeId")
            ref = f"e{backend}" if backend else "-"
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

    async def _scoped_nodes(self, scope: str, nodes: list[dict]) -> list[dict]:
        """Scope string → AX nodes to project. Ordinary scopes walk the main
        tree; an iframe scope swaps to the frame's own AX tree (Chrome keeps
        each frame's tree separate). Browser-side a11y and backendNodeId
        resolution reach into cross-origin frames too — observe and act both
        work; only JS extract is confined to the top frame's origin."""
        backend_id = await self._resolve_scope(scope)
        desc = await self._send("DOM.describeNode", {"backendNodeId": backend_id, "depth": 1})
        if desc["node"].get("nodeName") == "IFRAME":
            cd = desc["node"].get("contentDocument")
            if cd is None:
                raise BrowserError("frame has no loaded document")
            # Chrome's a11y is browser-side and backendNodeId resolution
            # routes into OOPIF contexts — cross-origin frame contents are
            # observable and actionable the same as same-origin ones.
            q = await self._send(
                "Accessibility.queryAXTree", {"backendNodeId": cd["backendNodeId"]}
            )
            return q.get("nodes", [])
        by_id = {n["nodeId"]: n for n in nodes}
        root = next((n for n in nodes if n.get("backendDOMNodeId") == backend_id), None)
        if root is None:
            raise BrowserError(f"scope not in accessibility tree: {scope}")
        # AX subtree walk — project every non-ignored role inside the
        # region (scoped observe exists to reach role-filtered content
        # like table rows; the element cap still applies).
        scope_ids: set[str] = set()
        stack = [root["nodeId"]]
        while stack:
            nid = stack.pop()
            if nid in scope_ids or nid not in by_id:
                continue
            scope_ids.add(nid)
            stack.extend(by_id[nid].get("childIds") or [])
        return [n for n in nodes if n["nodeId"] in scope_ids]

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

    async def act(self, action: str, ref: str = "", value: str | None = None) -> str:
        self.last_activity = time.monotonic()
        oid = None
        if ref and action != "navigate":
            if not ref[1:].isdigit() or not ref.startswith("e"):
                raise BrowserError(f"unknown element ref: {ref!r}")
            backend_id = int(ref[1:])
            node = await self._send("DOM.resolveNode", {"backendNodeId": backend_id})
            oid = node["object"]["objectId"]
        if action == "click":
            if oid is None:
                raise BrowserError("click requires a target ref")
            await self._send(
                "Runtime.callFunctionOn",
                {
                    "objectId": oid,
                    "functionDeclaration": (
                        "function(){(this.nodeType===1?this:this.parentElement).click()}"
                    ),
                },
            )
        elif action == "type":
            if oid is None:
                raise BrowserError("type requires a target ref")
            # Focus + select existing text, then Input.insertText — the
            # trusted input pipeline, so React/Vue controlled inputs see a
            # real text insertion (a raw el.value= write is invisible to them).
            await self._send(
                "Runtime.callFunctionOn",
                {
                    "objectId": oid,
                    "functionDeclaration": (
                        "function(){const el=this.nodeType===1?this:this.parentElement;"
                        "el.focus();if(el.select)el.select()}"
                    ),
                },
            )
            await self._send("Input.insertText", {"text": value or ""})
        elif action == "select":
            if oid is None:
                raise BrowserError("select requires a target ref (the <select> element)")
            await self._send(
                "Runtime.callFunctionOn",
                {
                    "objectId": oid,
                    "functionDeclaration": (
                        "function(v){const el=this.nodeType===1?this:this.parentElement;"
                        "el.value=v;"
                        "el.dispatchEvent(new Event('change',{bubbles:true}))}"
                    ),
                    "arguments": [{"value": value}],
                },
            )
        elif action == "keypress":
            # Trusted key events via Input domain — Enter submits forms,
            # Tab moves focus, Escape dismisses. Named keys only; for text
            # use 'type'. dispatchKeyEvent targets the *focused* element —
            # focus the ref first when one is given.
            if oid is not None:
                await self._send(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": oid,
                        "functionDeclaration": (
                            "function(){(this.nodeType===1?this:this.parentElement).focus()}"
                        ),
                    },
                )
            key = value or "Enter"
            vk = _KEY_CODES.get(key)
            # Puppeteer's sequence: down → char (if the key produces text,
            # which is what triggers form submission on Enter) → up.
            seq: list[tuple[str, dict]] = [("rawKeyDown", {})]
            if key in _KEY_TEXT:
                seq.append(("char", {"text": _KEY_TEXT[key]}))
            seq.append(("keyUp", {}))
            for t, extra in seq:
                params: dict = {"type": t, "key": key, "code": key, **extra}
                if vk is not None:
                    params["windowsVirtualKeyCode"] = vk
                await self._send("Input.dispatchKeyEvent", params)
        elif action == "hover":
            if oid is None:
                raise BrowserError("hover requires a target ref")
            box = await self._send(
                "Runtime.callFunctionOn",
                {
                    "objectId": oid,
                    "functionDeclaration": (
                        # AX refs can resolve to text nodes — climb to the
                        # element before measuring.
                        "function(){const el=this.nodeType===1?this:this.parentElement;"
                        "const r=el.getBoundingClientRect();"
                        "return {x:r.x+r.width/2,y:r.y+r.height/2}}"
                    ),
                    "returnByValue": True,
                },
            )
            if "exceptionDetails" in box or "value" not in box.get("result", {}):
                raise BrowserError("hover target has no measurable box")
            pt = box["result"]["value"]
            await self._send(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": pt["x"], "y": pt["y"]},
            )
        elif action == "navigate":
            # Models routinely put the URL in `target` instead of `value` —
            # accept either rather than erroring on a predictable mistake.
            url = value or (ref if "://" in ref else "")
            if not url:
                raise BrowserError("navigate requires a url value")
            await self.navigate(url)
        elif action == "scroll":
            if ref:
                # scroll the element into view
                await self._send(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": oid,
                        "functionDeclaration": (
                            "function(){const el=this.nodeType===1?this:"
                            "this.parentElement;el.scrollIntoView({block:'center'})}"
                        ),
                    },
                )
            else:
                # no ref — scroll the viewport; value: up/down/pixels
                delta = {"up": -600, "down": 600}.get(value or "down")
                try:
                    px = delta if delta is not None else int(value)
                except (TypeError, ValueError):
                    raise BrowserError(
                        "scroll value must be 'up', 'down', or pixel count"
                    ) from None
                await self._send(
                    "Runtime.evaluate",
                    {"expression": f"window.scrollBy(0,{px})"},
                )
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
