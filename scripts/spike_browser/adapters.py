"""W4 spike — raw-CDP browser adapter, the Browser module's foundation.

Decision already made: browser automation is built from scratch on the
DevTools Protocol — no Playwright/Selenium. This file proves the mechanics
the real module needs and measures whether the plan's provisional token
budgets (≤2000 initial / ≤800 post-action delta) survive contact with real
pages.

Interface mirrors the module contract:
    open(url) -> observation          (cold start + navigate + initial obs)
    observe() -> observation          (full bounded re-observation)
    act(action, ref, value) -> delta  (one state change + post-action delta)
    extract(query) -> data
    close()
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

CHROME = os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/"
    "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)

# Roles that matter to an agent — everything else is noise for the
# observation budget. Tightened after the spike: structural roles
# (row/cell/listitem) are what blew HN to 3853 tokens — they're excluded by
# default and reachable via a scoped observe. Interactive + landmark only.
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
MAX_ELEMENTS = 80  # hard cap; overflow reported as an omission marker


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

    def delta(self, prev: "Observation") -> str:
        """Changed/added/removed element lines vs a previous observation."""
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


# ---------------------------------------------------------------------------
# Adapter 1: raw CDP over websockets — zero framework, we own the protocol.
# ---------------------------------------------------------------------------


class CdpAdapter:
    name = "raw-cdp"

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._ws = None
        self._session: str | None = None
        self._msg_id = 0
        self._profile_dir: tempfile.TemporaryDirectory | None = None
        self._pending_events: list[dict] = []
        self._last_obs: Observation | None = None

    async def _send(self, method: str, params: dict | None = None, session: bool = True):
        import websockets

        self._msg_id += 1
        mid = self._msg_id
        msg: dict = {"id": mid, "method": method, "params": params or {}}
        if session and self._session:
            msg["sessionId"] = self._session
        await self._ws.send(json.dumps(msg))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=15)
            data = json.loads(raw)
            if data.get("id") == mid:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result", {})
            self._pending_events.append(data)

    async def open(self, url: str) -> Observation:
        import websockets

        self._profile_dir = tempfile.TemporaryDirectory(prefix="cdp-spike-")
        self._proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._profile_dir.name}",
                "--no-first-run",
                "--disable-extensions",
                "--mute-audio",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port_file = Path(self._profile_dir.name) / "DevToolsActivePort"
        for _ in range(100):
            if port_file.exists():
                break
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
        await self._send("Page.navigate", {"url": url})
        await self._wait_load()
        return await self.observe()

    async def _wait_load(self) -> None:
        # Event-driven wait: drain the pending queue / recv until loadEventFired.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for i, ev in enumerate(self._pending_events):
                if ev.get("method") == "Page.loadEventFired":
                    self._pending_events.pop(i)
                    return
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=0.5)
                self._pending_events.append(json.loads(raw))
            except TimeoutError:
                if self._proc.poll() is not None:
                    raise RuntimeError("browser exited") from None

    async def observe(self) -> Observation:
        tree = await self._send("Accessibility.getFullAXTree")
        doc = await self._send(
            "Runtime.evaluate", {"expression": "location.href + '|' + document.title"}
        )
        url, _, title = doc["result"]["value"].partition("|")
        elements: list[Element] = []
        omitted = 0
        for node in tree.get("nodes", []):
            role = (node.get("role") or {}).get("value", "")
            if role not in KEEP_ROLES or node.get("ignored"):
                continue
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
                    name=f"{omitted} elements omitted — call observe(scope=...) to inspect",
                )
            )
        obs = Observation(url=url, title=title, elements=elements)
        self._last_obs = obs
        return obs

    async def act(self, action: str, ref: str, value: str | None = None) -> str:
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
        else:
            raise ValueError(action)
        # Post-action delta — one act, one observation, per the module contract.
        prev = self._last_obs
        obs = await self.observe()
        return obs.delta(prev) if prev else obs.serialize()

    async def extract(self, query: str) -> str:
        if query == "table":
            expr = (
                "JSON.stringify([...document.querySelectorAll('#grid tbody tr')]"
                ".map(r=>[...r.cells].map(c=>c.textContent)))"
            )
            res = await self._send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return res["result"]["value"]
        raise ValueError(query)

    def browser_pids(self) -> list[int]:
        if not self._proc:
            return []
        out = subprocess.run(
            ["pgrep", "-f", self._profile_dir.name], capture_output=True, text=True
        ).stdout.split()
        return [int(p) for p in out]

    async def close(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        if self._profile_dir:
            self._profile_dir.cleanup()


ADAPTERS = {"raw-cdp": CdpAdapter}
