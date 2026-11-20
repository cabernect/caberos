"""Isolated local capture of the SAME React canvas used by PreviewPanel.

Only platform-owned compiled assets are served. The spec is injected over CDP,
not published by the HTTP server. No agent HTML, credentials, remote assets,
runtime downloads, or shared browser profiles enter this rendering process.
"""

import asyncio
import base64
import json
import mimetypes
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..browser.cdp import BrowserError, BrowserSession
from ..browser.runtime import find_browser_binary
from ..sandbox.workspace import resolve_within

_GATE = asyncio.Semaphore(2)
_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src data:; connect-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-src 'none'"
)


def renderer_root() -> Path:
    candidates = [Path(__file__).resolve().parents[4] / "frontend" / "dist"]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "frontend-dist")
    for candidate in candidates:
        if (candidate / "deck-render.html").is_file():
            return candidate
    raise ValueError(
        "Presentation renderer is unavailable. Build the frontend before exporting PDF/images."
    )


def _server(root: Path) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            rel = unquote(urlsplit(self.path).path).lstrip("/")
            if rel != "deck-render.html" and not rel.startswith("assets/"):
                self.send_error(404)
                return
            try:
                file = resolve_within(root, rel)
                data = file.read_bytes()
            except (ValueError, OSError):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            )
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def render(spec: dict, *, slides: list[int] | None = None, pdf=False):
    binary = find_browser_binary()
    if binary is None:
        raise ValueError(
            "A Chromium-family browser is required for PDF/image exports. Nothing was installed."
        )
    async with asyncio.timeout(90), _GATE:
        server = _server(renderer_root())
        with tempfile.TemporaryDirectory(prefix="caberos-deck-render-") as directory:
            browser = BrowserSession(binary, Path(directory))
            try:
                await browser.open("about:blank")
                await browser.set_viewport(1280, 720)
                # A platform-owned loopback document, not an agent-supplied URL.
                await browser._send(
                    "Page.navigate",
                    {
                        "url": f"http://127.0.0.1:{server.server_port}/deck-render.html",
                    },
                )
                await browser._wait_load()
                for _ in range(100):
                    if await browser.evaluate_json("typeof window.__renderDeck === 'function'"):
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise ValueError("Presentation renderer failed to initialize")
                indices = slides if slides is not None else list(range(len(spec["slides"])))
                images, total = {}, 0
                for group in [indices] if pdf else [[i] for i in indices]:
                    result = await browser.evaluate_json(
                        f"window.__renderDeck({json.dumps(spec)}, {json.dumps(group)})"
                    )
                    if not isinstance(result, dict):
                        raise ValueError("Presentation render failed")
                    if result.get("errors"):
                        raise ValueError("; ".join(result["errors"]))
                    if pdf:
                        output = await browser._send(
                            "Page.printToPDF",
                            {
                                "printBackground": True,
                                "preferCSSPageSize": True,
                                "marginTop": 0,
                                "marginBottom": 0,
                                "marginLeft": 0,
                                "marginRight": 0,
                            },
                        )
                        return base64.b64decode(output["data"])
                    output = await browser._send(
                        "Page.captureScreenshot",
                        {
                            "format": "png",
                            "captureBeyondViewport": False,
                            "clip": {"x": 0, "y": 0, "width": 1280, "height": 720, "scale": 1},
                        },
                    )
                    image = base64.b64decode(output["data"])
                    total += len(image)
                    if total > 50 * 1024 * 1024:
                        raise ValueError("Presentation raster exports exceed 50MB")
                    images[group[0]] = image
                return images
            except BrowserError as exc:
                raise ValueError(f"Local presentation renderer failed: {exc}") from exc
            finally:
                await browser.close()
                await asyncio.to_thread(server.shutdown)
                server.server_close()
