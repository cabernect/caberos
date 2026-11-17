import json
from io import BytesIO

import pytest
from pptx import Presentation

from agentos.artifacts.deck_spec import normalize
from agentos.artifacts.formats import deck, pptx


def motion_spec():
    return {
        "kind": "deck",
        "motion": {
            "transition": {"type": "slide", "duration_ms": 400},
            "entrance": {"type": "rise", "duration_ms": 250},
        },
        "slides": [
            {
                "id": "intro",
                "title": "Motion",
                "transition": {"type": "fade"},
                "blocks": [
                    {"id": "points", "type": "bullets", "items": ["One", "Two"], "reveal": "items"},
                    {
                        "type": "paragraph",
                        "text": "Final state",
                        "reveal": True,
                        "animation": {"type": "fade"},
                    },
                ],
            },
        ],
    }


def test_motion_survives_creation_revision_and_static_pptx(tmp_path):
    data = deck.build(motion_spec(), tmp_path)
    revised = json.loads(deck.revise(data, [{"op": "set_title", "title": "Revised"}], tmp_path))
    assert revised["motion"]["entrance"] == {"type": "rise", "duration_ms": 250}
    assert revised["slides"][0]["transition"]["duration_ms"] == 300
    assert revised["slides"][0]["blocks"][0]["reveal"] == "items"
    assert revised["slides"][0]["blocks"][1]["id"] == "intro.b2"
    prs = Presentation(BytesIO(pptx.build(revised, tmp_path)))
    text = "\n".join(s.text for s in prs.slides[0].shapes if s.has_text_frame)
    assert all(value in text for value in ["One", "Two", "Final state"])


@pytest.mark.parametrize(
    "motion",
    [
        None,
        [],
        {"unknown": {}},
        {"transition": {"type": "rise"}},
        {"entrance": {"type": "slide"}},
        {"entrance": {"type": "javascript"}},
        {"transition": {"duration_ms": -1}},
        {"transition": {"duration_ms": 2001}},
        {"transition": {"duration_ms": True}},
        {"entrance": {"css": "anything"}},
    ],
)
def test_invalid_motion_is_rejected(motion):
    spec = motion_spec()
    spec["motion"] = motion
    with pytest.raises(ValueError):
        normalize(spec)


@pytest.mark.parametrize(
    "block",
    [
        {"type": "paragraph", "reveal": "items"},
        {"type": "paragraph", "reveal": 1},
        {"type": "paragraph", "animation": {"type": "spin"}},
    ],
)
def test_invalid_block_motion_is_rejected(block):
    with pytest.raises(ValueError):
        normalize({"slides": [{"blocks": [block]}]})
