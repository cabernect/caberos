"""Deterministic Markdown -> speakable text for Read Aloud.

Rules (W10): strip Markdown syntax, speak link labels rather than URLs,
preserve prose and list order, keep inline code in prose. Omit fenced/
indented code, raw HTML, tables, and images with an honest "(… omitted)"
indication — never narrate raw Markdown, JSON payloads, or URLs.

No model call, no paraphrasing, no fetching linked content.
"""

import re

# Bumped when rendering rules change — cached audio keys on this so an
# older rendering never replays under a new renderer.
RENDERER_VERSION = 1

_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|")
_TABLE_SEP = re.compile(r"^\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_HRULE = re.compile(r"^\s{0,3}([-*_]\s*){3,}$")
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?")
_HTML_LINE = re.compile(r"^\s*</?[a-zA-Z][^>]*>\s*$")
_TAG = re.compile(r"<[^>]+>")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_EMPHASIS = re.compile(r"\*{1,3}|(?<!\w)_{1,3}|_{1,3}(?!\w)")
_INDENTED_CODE = re.compile(r"^(?:    |\t)\S")
_WS = re.compile(r"[ \t]+")
_OMITTED_ONLY = re.compile(r"(\((code|table|image) omitted\)|\(link\)|\s)+")

CODE_OMITTED = "(code omitted)"
TABLE_OMITTED = "(table omitted)"
IMAGE_OMITTED = "(image omitted)"
LINK_PLACEHOLDER = "(link)"


def _prose(line: str) -> str:
    """Reduce one Markdown line to speakable text; may return empty."""
    line = _MD_IMAGE.sub(IMAGE_OMITTED, line)
    line = _MD_LINK.sub(lambda m: m.group(1).strip() or LINK_PLACEHOLDER, line)
    line = _BARE_URL.sub(LINK_PLACEHOLDER, line)
    line = _TAG.sub("", line)
    line = _INLINE_CODE.sub(lambda m: m.group(1), line)
    line = _EMPHASIS.sub("", line)
    return _WS.sub(" ", line).strip()


def render_speakable(markdown: str) -> str:
    """Render Markdown source to a deterministic speakable string.

    Empty output means no speakable prose — callers offer no read aloud.
    """
    chunks: list[str] = []
    in_fence = False
    in_code = in_table = False

    def flush() -> None:
        nonlocal in_code, in_table
        if in_code:
            chunks.append(CODE_OMITTED)
            in_code = False
        if in_table:
            chunks.append(TABLE_OMITTED)
            in_table = False

    for raw in markdown.splitlines():
        if _FENCE.match(raw):
            if in_fence:
                in_fence = False
                in_code = True
                flush()
            else:
                flush()
                in_fence = True
            continue
        if in_fence:
            continue
        # "---" is a horizontal rule; table separators always contain "|".
        if _TABLE_ROW.match(raw) or (_TABLE_SEP.match(raw) and not _HRULE.match(raw)):
            in_table = True
            continue
        if _INDENTED_CODE.match(raw):
            in_code = True
            continue
        if _HTML_LINE.match(raw):
            continue
        flush()
        line = raw
        line = _HEADING.sub("", line)
        line = _BLOCKQUOTE.sub("", line)
        if _HRULE.match(line):
            continue
        ordered = _ORDERED.match(line)
        if ordered:
            line = f"{ordered.group(2)}. {line[ordered.end() :]}"
        else:
            line = _BULLET.sub("", line)
        line = _prose(line)
        if line:
            chunks.append(line)
    if in_fence:
        in_code = True
    flush()
    return _WS.sub(" ", " ".join(chunks)).strip()


def has_speakable_text(markdown: str) -> bool:
    """False when only omissions remain — no prose to read aloud."""
    return bool(_OMITTED_ONLY.sub("", render_speakable(markdown)).strip())
