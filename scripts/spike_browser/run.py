"""W4 spike runner — measure the raw-CDP adapter against the plan's budgets.

Usage:  cd backend && uv run python ../scripts/spike_browser/run.py [--live]

Tasks (identical shape to what the real module will drive):
    T1 cold-open + initial observation   -> cold-start latency, obs tokens
    T2 no-op re-observe                  -> delta should be ~0 tokens
    T3 click counter                     -> act latency, post-action delta tokens
    T4 type into filter                  -> act latency, delta tokens
    T5 extract table                     -> extraction reliability

Metrics: wall latency (monotonic), browser RSS via `ps`, observation tokens
via litellm.token_counter (same counter the harness uses).
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adapters import CdpAdapter  # noqa: E402

PAGE = Path(__file__).parent / "page.html"


def tokens(text: str) -> int:
    try:
        import litellm

        return litellm.token_counter(model="gpt-4o", text=text)
    except Exception:
        return max(1, len(text) // 4)


def rss_mb(pids: list[int]) -> float:
    if not pids:
        return 0.0
    total = 0
    for pid in pids:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        total += int(out) if out.isdigit() else 0
    return total / 1024  # KB -> MB


def serve(page: Path) -> tuple[http.server.HTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(page.parent))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}/{page.name}"


async def run_local() -> dict:
    httpd, url = serve(PAGE)
    adapter = CdpAdapter()
    m: dict = {"url": url}
    try:
        t = time.monotonic()
        obs = await adapter.open(url)
        m["cold_open_s"] = round(time.monotonic() - t, 3)
        m["mem_after_open_mb"] = round(rss_mb(adapter.browser_pids()), 1)
        m["obs_tokens"] = tokens(obs.serialize())
        m["obs_elements"] = len(obs.elements)

        t = time.monotonic()
        obs2 = await adapter.observe()
        m["reobserve_s"] = round(time.monotonic() - t, 3)
        m["noop_delta"] = obs2.delta(obs)

        button = next(e for e in obs2.elements if "count" in e.name.lower())
        t = time.monotonic()
        delta = await adapter.act("click", button.ref)
        m["click_s"] = round(time.monotonic() - t, 3)
        m["click_delta_tokens"] = tokens(delta)
        m["click_delta"] = delta

        box = next(e for e in obs2.elements if e.role == "textbox")
        t = time.monotonic()
        delta = await adapter.act("type", box.ref, "Item 1")
        m["type_s"] = round(time.monotonic() - t, 3)
        m["type_delta_tokens"] = tokens(delta)
        m["type_delta"] = delta

        t = time.monotonic()
        table = await adapter.extract("table")
        m["extract_s"] = round(time.monotonic() - t, 3)
        rows = json.loads(table)
        m["extract_rows"] = len(rows)
        m["extract_ok"] = rows[0][0] == "SKU-1000" and rows[29][2] == "107.30"

        await asyncio.sleep(2)  # let it settle for idle reading
        m["mem_idle_mb"] = round(rss_mb(adapter.browser_pids()), 1)
        return m
    finally:
        await adapter.close()
        httpd.shutdown()


LIVE_URLS = [
    "https://news.ycombinator.com",  # server-rendered but real-world shape
    "https://example.com",  # minimal baseline
]


async def run_live() -> list[dict]:
    results = []
    for url in LIVE_URLS:
        adapter = CdpAdapter()
        m: dict = {"url": url}
        try:
            t = time.monotonic()
            obs = await adapter.open(url)
            m["cold_open_s"] = round(time.monotonic() - t, 3)
            m["mem_after_open_mb"] = round(rss_mb(adapter.browser_pids()), 1)
            m["obs_tokens"] = tokens(obs.serialize())
            m["obs_elements"] = len(obs.elements)
            m["ok"] = True
        except Exception as e:  # noqa: BLE001 — spike records failures, doesn't hide them
            m["ok"] = False
            m["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            await adapter.close()
        results.append(m)
    return results


async def main() -> None:
    print("== local dynamic page ==")
    local = await run_local()
    for k, v in local.items():
        print(f"  {k}: {v}")
    if "--live" in sys.argv:
        print("== live sites ==")
        for m in await run_live():
            print(f"  {m}")


if __name__ == "__main__":
    asyncio.run(main())
