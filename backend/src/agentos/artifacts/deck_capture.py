"""Deck capture — bounded, stable per-slide renders of an admitted deck.

Renders one immutable revision's self-contained .html in the managed
Chrome-for-Testing runtime (headless, fixed 1280×720 viewport = the slide
canvas), drives the deck's own `goto` bridge for deterministic states, and
returns per-slide metrics + PNG bytes. This is the visual verify step:
structural validate() can't see overflow, blank slides, or unreadable
shrink-to-fit — the capture can.

Trust model: the deck bytes come from CaberOS's own admitted-artifact
pipeline (marker + valid spec + platform-runtime scripts only, CSP
connect-src 'none'), loaded via file:// inside a throwaway browser
profile. The document cannot egress, touch app origins, or reach the
operator's real browser profile. Captures are evidence, not authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import time
from pathlib import Path

from ..browser import runtime as browser_runtime
from ..browser.cdp import BrowserError, BrowserSession
from .formats import html as deck_fmt

logger = logging.getLogger(__name__)

CAPTURE_VERSION = "deckcap-v1"
VIEWPORT_W = 1280
VIEWPORT_H = 720
_MAX_SLIDES = deck_fmt.MAX_SLIDES
# goto reveal=999 clamps to the slide's own .rv count → the fully-built
# (final) state, which is what verification cares about.
_FINAL_REVEAL = 999
_SETTLE_TIMEOUT_S = 5.0
_SLIDE_TIMEOUT_S = 15.0
_DECK_TIMEOUT_S = 180.0


class DeckCaptureError(Exception):
    """Capture refused or the render runtime failed — message is operator-safe."""


def _slide_metrics_js() -> str:
    return """(() => {
  const s = document.querySelector('.slide.active');
  if (!s) return null;
  const r = s.getBoundingClientRect();
  const cs = getComputedStyle(s);
  const txt = (s.textContent || '').replace(/\\s+/g, ' ').trim();
  const imgs = [...s.querySelectorAll('img')];
  const brokenImgs = imgs.filter(i => !i.complete || i.naturalWidth === 0).length;
  return {
    rect: {x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height},
    scrollH: s.scrollHeight, clientH: s.clientHeight,
    overflow: s.scrollHeight > s.clientHeight + 4,
    dfs: parseFloat(cs.getPropertyValue('--dfs')) || 1,
    rvTotal: s.querySelectorAll('.rv').length,
    rvOn: s.querySelectorAll('.rv.on').length,
    textChars: txt.length,
    // A slide is 'blank' when nothing readable or visual rendered —
    // catches hidden-by-reveal mistakes and empty fragments.
    blank: txt.length < 3 && imgs.length === 0,
    brokenImgs,
    title: (s.querySelector('.slide-title') || {}).textContent || '',
    animating: s.getAnimations ? s.getAnimations().length : 0,
  };
})()"""


async def _wait_deck_ready(session: BrowserSession, count: int) -> None:
    """Poll until the runtime has activated slide 0 of `count` slides."""
    deadline = time.monotonic() + _SLIDE_TIMEOUT_S
    while time.monotonic() < deadline:
        n = await session.evaluate_json("document.querySelectorAll('#deck > .slide').length")
        active = await session.evaluate_json("!!document.querySelector('.slide.active')")
        if n == count and active:
            return
        await asyncio.sleep(0.05)
    raise DeckCaptureError("deck runtime did not initialize")


async def _settle(session: BrowserSession) -> None:
    """Wait for slide transitions/reveals to finish — deterministic, not timed."""
    deadline = time.monotonic() + _SETTLE_TIMEOUT_S
    while time.monotonic() < deadline:
        anim = await session.evaluate_json(
            "(() => { const s = document.querySelector('.slide.active');"
            " return s && s.getAnimations ? s.getAnimations().length : 0; })()"
        )
        if not anim:
            return
        await asyncio.sleep(0.05)
    # Animations that never end shouldn't block capture — proceed honestly.


async def _goto(session: BrowserSession, index: int, reveal: int) -> dict:
    await session.evaluate_json(
        f"window.postMessage({{caberos:'deck',v:1,type:'goto',index:{index},reveal:{reveal}}},'*')"
    )
    await _settle(session)
    metrics = await session.evaluate_json(_slide_metrics_js())
    if not metrics:
        raise DeckCaptureError(f"slide {index} did not render")
    return metrics


async def _shot(session: BrowserSession) -> bytes:
    # Viewport is exactly 16:9, so the letterboxed slide fills it edge to
    # edge — a full-viewport PNG IS the slide capture (scrollbars included,
    # which is honest evidence when shrink-to-fit bottoms out).
    return await session.screenshot()


async def capture_deck(
    data: bytes,
    *,
    slides: list[int] | None = None,
    reveal: int = _FINAL_REVEAL,
) -> dict:
    """Render slide captures for admitted deck bytes.

    Returns {runtime, slide_count, viewport, slides:[{index, metrics, png}]}.
    `slides` restricts the set (still bounded by MAX_SLIDES); `reveal` is the
    exact .rv count to build (999 = fully revealed final state).
    """
    info = deck_fmt.admission(data)
    if info is None:
        raise DeckCaptureError("not an admitted deck")
    binary = browser_runtime.find_browser_binary()
    if binary is None:
        raise DeckCaptureError("capture runtime unavailable — install the managed browser first")

    indices = slides if slides is not None else list(range(info["slides"]))
    indices = sorted({i for i in indices if 0 <= i < info["slides"]})
    if not indices:
        raise DeckCaptureError("no valid slide indices requested")
    if len(indices) > _MAX_SLIDES:
        raise DeckCaptureError(f"capture bounded at {_MAX_SLIDES} slides")

    deck_hash = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="deckcap-") as tmp:
        tmp_path = Path(tmp)
        deck_file = tmp_path / "deck.html"
        deck_file.write_bytes(data)
        profile = tmp_path / "profile"
        profile.mkdir()
        session = BrowserSession(binary, profile)
        try:
            await session.open("about:blank")
            await session.set_viewport(VIEWPORT_W, VIEWPORT_H)
            await session.navigate_local(deck_file)
            await _wait_deck_ready(session, info["slides"])
            out = []
            deadline = time.monotonic() + _DECK_TIMEOUT_S
            for idx in indices:
                if time.monotonic() > deadline:
                    raise DeckCaptureError("capture timed out")
                metrics = await _goto(session, idx, reveal)
                png = await _shot(session)
                metrics.pop("rect", None)  # page coords are capture-internal
                metrics.pop("animating", None)
                out.append(
                    {
                        "index": idx,
                        "reveal": reveal,
                        "metrics": metrics,
                        "png": png,
                    }
                )
        except BrowserError as e:
            raise DeckCaptureError(f"capture render failed: {e}") from e
        finally:
            try:
                await session.close()
            except Exception:
                logger.debug("deck capture session close failed", exc_info=True)

    return {
        "version": CAPTURE_VERSION,
        "deck_sha256": deck_hash,
        "runtime": info["runtime"],
        "title": info.get("title"),
        "slide_count": info["slides"],
        "viewport": {"width": VIEWPORT_W, "height": VIEWPORT_H},
        "reveal": reveal,
        "slides": out,
    }
