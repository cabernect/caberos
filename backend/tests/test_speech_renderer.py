"""Deterministic speech-renderer fixtures — Markdown to speakable text (W10)."""

import pytest

from agentos.speech.renderer import (
    CODE_OMITTED,
    IMAGE_OMITTED,
    LINK_PLACEHOLDER,
    TABLE_OMITTED,
    has_speakable_text,
    render_speakable,
)


@pytest.mark.parametrize(
    "source,want",
    [
        ("Hello world.", "Hello world."),
        ("## Title\nBody **bold** and _italic_.", "Title Body bold and italic."),
        ("Use `run_query()` for that.", "Use run_query() for that."),
        ("See [the docs](https://example.com/docs) first.", "See the docs first."),
        ("Visit https://example.com/x for more.", f"Visit {LINK_PLACEHOLDER} for more."),
        ("1. first\n2. second", "1. first 2. second"),
        ("- alpha\n- beta", "alpha beta"),
        ("> quoted text", "quoted text"),
        ("before\n\n---\n\nafter", "before after"),
        ("`npm i`", "npm i"),
        ("[](https://x)", LINK_PLACEHOLDER),
    ],
)
def test_inline_and_prose_rendering(source, want):
    assert render_speakable(source) == want


@pytest.mark.parametrize(
    "source",
    [
        "```python\nprint('x')\n```",
        "Before\n```\nraw()\n```\nafter",
        "~~~\ncode\n~~~",
        '```json\n{"key": "value"}\n```',
        "    indented_code()",
        "```\nunterminated",
    ],
)
def test_code_is_omitted_with_honest_marker(source):
    out = render_speakable(source)
    assert CODE_OMITTED in out
    assert "print" not in out and "raw" not in out and "key" not in out
    if "Before" in source:
        assert out.startswith("Before") and out.endswith("after")


@pytest.mark.parametrize(
    "source",
    [
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "text\n| col |\n| --- |\n| v |\nmore",
    ],
)
def test_tables_are_omitted_with_marker(source):
    out = render_speakable(source)
    assert TABLE_OMITTED in out
    assert "|" not in out


def test_images_omitted_but_alt_link_text_kept():
    out = render_speakable("![chart](https://x/img.png) and [label](https://x)")
    assert IMAGE_OMITTED in out
    assert "label" in out
    assert "https" not in out


def test_inline_html_stripped_blocks_omitted():
    out = render_speakable("<div>\nText <b>bold</b> stays\n</div>")
    assert "Text bold stays" in out
    assert "<" not in out


@pytest.mark.parametrize(
    "source",
    [
        "```\nonly code\n```",
        "![only](https://x/i.png)",
        "https://example.com",
        "| a |\n| --- |",
        "",
        "   \n\n",
    ],
)
def test_nothing_speakable_means_no_read_aloud(source):
    assert has_speakable_text(source) is False


def test_mixed_message_keeps_prose_order():
    source = (
        "Here's the result:\n\n"
        "```\nsecret_payload()\n```\n\n"
        "| a | b |\n| --- | --- |\n"
        "And [the report](https://x) is done."
    )
    out = render_speakable(source)
    assert out == (f"Here's the result: {CODE_OMITTED} {TABLE_OMITTED} And the report is done.")


def test_no_markdown_syntax_survives():
    out = render_speakable("## H\n**b** _i_ `c` [t](u) ![i](u)\n> q\n- li")
    for token in ("#", "*", "_", "`", "[", "]", "(h", "![", ">"):
        assert token not in out
