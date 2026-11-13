"""Deck capture — bounded slide renders for admitted decks (W2H slice 6)."""

import pytest

from agentos.artifacts import deck_capture
from agentos.artifacts.formats import html as deck_fmt


def _deck(spec_overrides=None):
    spec = {
        "title": "Capture Test",
        "slides": [
            {"title": "One", "blocks": [{"type": "paragraph", "text": "hello"}]},
            {
                "title": "Two",
                "blocks": [
                    {"type": "bullets", "items": ["a", "b"]},
                    {"type": "paragraph", "text": "tail", "reveal": True},
                ],
            },
        ],
    }
    if spec_overrides:
        spec.update(spec_overrides)
    return deck_fmt.build(spec, "/tmp")


def test_capture_refuses_non_deck():
    with pytest.raises(deck_capture.DeckCaptureError, match="not an admitted"):
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            deck_capture.capture_deck(b"<html><body>hi</body></html>")
        )


def test_capture_refuses_bad_slide_range():
    data = _deck()
    import asyncio

    # Out-of-range indices are dropped; a set with nothing valid refuses
    # before any browser launches.
    with pytest.raises(deck_capture.DeckCaptureError, match="no valid slide"):
        asyncio.get_event_loop().run_until_complete(
            deck_capture.capture_deck(data, slides=[98, 99])
        )


def test_parse_reveal_and_slides():
    from fastapi import HTTPException

    from agentos.api.agent_files import _parse_reveal, _parse_slides

    assert _parse_reveal("final") == 999
    assert _parse_reveal("3") == 3
    with pytest.raises(HTTPException):
        _parse_reveal("abc")
    with pytest.raises(HTTPException):
        _parse_reveal("1000")
    assert _parse_slides("", 4) is None
    assert _parse_slides("2,0,2", 4) == [0, 2]
    with pytest.raises(HTTPException):
        _parse_slides("9", 4)
    with pytest.raises(HTTPException):
        _parse_slides("x", 4)


@pytest.mark.skipif(
    __import__("agentos.browser.runtime", fromlist=["x"]).find_browser_binary() is None,
    reason="managed browser runtime not installed",
)
async def test_capture_real_deck():
    """End-to-end: build → admit → render slides in managed Chrome."""
    data = _deck()
    result = await deck_capture.capture_deck(data)
    assert result["runtime"] == deck_fmt.RUNTIME_VERSION
    assert result["slide_count"] == 2
    assert result["viewport"] == {"width": 1280, "height": 720}
    assert len(result["slides"]) == 2
    for s in result["slides"]:
        assert s["png"][:8] == b"\x89PNG\r\n\x1a\n"
        m = s["metrics"]
        assert m["blank"] is False
        assert m["textChars"] > 0
        assert "overflow" in m and "dfs" in m


@pytest.mark.skipif(
    __import__("agentos.browser.runtime", fromlist=["x"]).find_browser_binary() is None,
    reason="managed browser runtime not installed",
)
async def test_capture_reveal_states():
    """reveal=0 vs final must produce different deterministic states."""
    data = _deck()
    hidden = await deck_capture.capture_deck(data, slides=[1], reveal=0)
    final = await deck_capture.capture_deck(data, slides=[1], reveal=999)
    m0 = hidden["slides"][0]["metrics"]
    m1 = final["slides"][0]["metrics"]
    assert m0["rvOn"] == 0 and m0["rvTotal"] == 1
    assert m1["rvOn"] == 1 and m1["rvTotal"] == 1
    assert hidden["slides"][0]["png"] != final["slides"][0]["png"]
