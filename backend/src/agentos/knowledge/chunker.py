"""Markdown-aware text chunking for local knowledge indexing.

Two layers:

- ``chunk_markdown`` / ``chunk_extracted_blocks`` — legacy flat splitting,
  still used as the leaf-window helper.
- ``chunk_blocks`` — the RAG v2 pipeline: dispatches on ``block_type`` to a
  per-type strategy (prose | tabular | singleton) and emits a uniform
  ``ChunkNode`` tree of parents (expansion-only) and children (retrievable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extractors import ExtractedBlock


@dataclass(frozen=True)
class MarkdownChunk:
    """A bounded text chunk with the heading context it was extracted from."""

    text: str
    heading_path: list[str]
    token_count: int
    page_number: int | None = None
    sheet_name: str | None = None
    source_location: str | None = None
    block_type: str = "paragraph"
    ordinal: int = 0


@dataclass(frozen=True)
class ChunkingConfig:
    """Corpus-state chunk parameters (snapshot into index generations)."""

    parent_tokens: int = 450
    child_tokens: int = 120
    child_overlap: int = 20
    table_row_limit: int = 150


@dataclass
class ChunkNode:
    """One node in the parent/child chunk tree.

    ``kind`` is ``parent`` (expansion-only container) or ``child``
    (retrievable unit; ``parent_id`` links back when it has a parent).
    Legacy flat rows keep ``kind='chunk'`` on the DB side.
    """

    text: str
    heading_path: list[str]
    token_count: int
    kind: str  # "parent" | "child"
    page_number: int | None = None
    sheet_name: str | None = None
    source_location: str | None = None
    block_type: str = "paragraph"
    children: list[ChunkNode] = field(default_factory=list)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def chunk_markdown(
    text: str,
    *,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[MarkdownChunk]:
    """Split Markdown or plain text into overlapping, heading-aware chunks.

    Token counts use whitespace-separated words as a deterministic local
    approximation. Heading context is included in each chunk's text and
    counted against its budget.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be between zero and max_tokens - 1")

    heading_stack: list[str] = []
    sections: list[tuple[list[str], list[str]]] = []
    content: list[str] = []

    def flush() -> None:
        if content:
            sections.append((heading_stack.copy(), content.copy()))
            content.clear()

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(match.group(2))
        elif line.strip():
            content.extend(line.split())
    flush()

    chunks: list[MarkdownChunk] = []
    for heading_path, words in sections:
        prefix = heading_path
        prefix_count = len(prefix)
        if prefix_count >= max_tokens:
            prefix = prefix[: max_tokens - 1]
            prefix_count = len(prefix)

        start = 0
        while start < len(words):
            available = max_tokens - prefix_count
            end = min(start + available, len(words))
            chunk_words = words[start:end]
            chunk_text = "\n".join([*prefix, " ".join(chunk_words)]).strip()
            chunks.append(
                MarkdownChunk(
                    text=chunk_text,
                    heading_path=heading_path,
                    token_count=len(chunk_text.split()),
                )
            )
            if end == len(words):
                break
            start = end - overlap_tokens

    return chunks


def chunk_extracted_blocks(
    blocks: list[ExtractedBlock],
    *,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[MarkdownChunk]:
    """Chunk normalized blocks while preserving format-specific source metadata."""
    chunks: list[MarkdownChunk] = []
    for ordinal, block in enumerate(blocks):
        heading_path = block.heading_path
        available = max_tokens - len(heading_path)
        if available <= 0:
            raise ValueError("max_tokens must leave room for heading context")
        for chunk in chunk_markdown(
            block.text,
            max_tokens=available,
            overlap_tokens=min(overlap_tokens, available - 1),
        ):
            chunk_text = "\n".join([*heading_path, chunk.text]).strip()
            chunks.append(
                MarkdownChunk(
                    text=chunk_text,
                    heading_path=heading_path,
                    token_count=len(chunk_text.split()),
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                    source_location=block.source_location,
                    block_type=block.block_type,
                    ordinal=ordinal,
                )
            )
    return chunks


def _tokens(text: str) -> int:
    return len(text.split())


def _with_heading_prefix(heading_path: list[str], body: str) -> str:
    return "\n".join([*heading_path, body]).strip() if heading_path else body


def _prose_nodes(
    words: list[str],
    heading_path: list[str],
    block_meta: dict,
    config: ChunkingConfig,
) -> list[ChunkNode]:
    """Split one heading-section's words into bounded parents + windowed children.

    A section short enough to be one child becomes a standalone child with no
    parent — a parent identical to its only child carries no extra context.
    """
    nodes: list[ChunkNode] = []
    start = 0
    while start < len(words):
        parent_words = words[start : start + config.parent_tokens]
        parent_body = " ".join(parent_words)
        if _tokens(parent_body) <= config.child_tokens:
            text = _with_heading_prefix(heading_path, parent_body)
            nodes.append(
                ChunkNode(
                    text=text,
                    heading_path=heading_path,
                    token_count=_tokens(text),
                    kind="child",
                    **block_meta,
                )
            )
            start += config.parent_tokens
            continue

        parent_text = _with_heading_prefix(heading_path, parent_body)
        parent = ChunkNode(
            text=parent_text,
            heading_path=heading_path,
            token_count=_tokens(parent_text),
            kind="parent",
            **block_meta,
        )
        c_start = 0
        while c_start < len(parent_words):
            c_end = min(c_start + config.child_tokens, len(parent_words))
            child_body = " ".join(parent_words[c_start:c_end])
            child_text = _with_heading_prefix(heading_path, child_body)
            parent.children.append(
                ChunkNode(
                    text=child_text,
                    heading_path=heading_path,
                    token_count=_tokens(child_text),
                    kind="child",
                    **block_meta,
                )
            )
            if c_end == len(parent_words):
                break
            c_start = c_end - config.child_overlap
        nodes.append(parent)
        start += config.parent_tokens
    return nodes


def _row_cells(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _tabular_nodes(
    block: ExtractedBlock,
    config: ChunkingConfig,
) -> list[ChunkNode]:
    """Split a table/sheet block into row-bounded regions and row-group children.

    A row is atomic — never split mid-row. The first row is the header and is
    prepended to every child so rows are self-contained. Region parents close
    at whichever bound hits first: ``table_row_limit`` rows or
    ``parent_tokens``.
    """
    rows = _row_cells(block.text)
    if not rows:
        return []
    header, data_rows = rows[0], rows[1:]
    sheet = block.sheet_name
    base_location = block.source_location or ""

    # Reuse the extractor's column span so child citations stay cell-shaped
    # (Sheet!A5:E12), not malformed (Sheet!A5:12).
    col_start, col_end = "A", ""
    span = re.fullmatch(r"(.+)!([A-Z]+)\d+:([A-Z]+)\d+", base_location)
    if span:
        col_start, col_end = span.group(2), span.group(3)

    def _location(first_row: int, last_row: int) -> str:
        if sheet:
            # Sheet rows are 1-based; row 1 is the header.
            return f"{sheet}!{col_start}{first_row}:{col_end}{last_row}"
        prefix = base_location or "table"
        return f"{prefix} rows {first_row}-{last_row}"

    meta = {
        "heading_path": block.heading_path,
        "page_number": None,
        "sheet_name": sheet,
        "block_type": block.block_type,
    }
    # Single data row → one standalone child, no parent needed.
    if not data_rows:
        text = _with_heading_prefix(block.heading_path, header)
        return [
            ChunkNode(
                text=text,
                token_count=_tokens(text),
                kind="child",
                source_location=_location(1, 1),
                **meta,
            )
        ]

    nodes: list[ChunkNode] = []
    region_start = 0  # index into data_rows (0-based; sheet row = idx + 2)
    while region_start < len(data_rows):
        region_rows: list[str] = []
        region_tokens = _tokens(header)
        end = region_start
        while end < len(data_rows):
            row = data_rows[end]
            new_tokens = region_tokens + _tokens(row) + 1
            if region_rows and (
                len(region_rows) >= config.table_row_limit or new_tokens > config.parent_tokens
            ):
                break
            region_rows.append(row)
            region_tokens = new_tokens
            end += 1

        first_sheet_row = region_start + 2
        last_sheet_row = end + 1
        region_body = "\n".join([header, *region_rows])
        parent_text = _with_heading_prefix(block.heading_path, region_body)

        # Children: header + row groups bounded by child_tokens.
        children: list[ChunkNode] = []
        c_start = 0
        while c_start < len(region_rows):
            child_rows: list[str] = []
            child_tokens = _tokens(header)
            c_end = c_start
            while c_end < len(region_rows):
                row_tokens = _tokens(region_rows[c_end])
                if child_rows and child_tokens + row_tokens + 1 > config.child_tokens:
                    break
                child_rows.append(region_rows[c_end])
                child_tokens += row_tokens + 1
                c_end += 1
            child_first = first_sheet_row + c_start
            child_last = first_sheet_row + c_end - 1
            child_body = "\n".join([header, *child_rows])
            child_text = _with_heading_prefix(block.heading_path, child_body)
            children.append(
                ChunkNode(
                    text=child_text,
                    token_count=_tokens(child_text),
                    kind="child",
                    source_location=_location(child_first, child_last),
                    **meta,
                )
            )
            c_start = c_end

        # A region that produced a single child covering the whole region is
        # emitted as a standalone child — the parent adds no context.
        if len(children) == 1:
            nodes.append(children[0])
        else:
            nodes.append(
                ChunkNode(
                    text=parent_text,
                    token_count=_tokens(parent_text),
                    kind="parent",
                    source_location=_location(first_sheet_row, last_sheet_row),
                    children=children,
                    **meta,
                )
            )
        region_start = end
    return nodes


def chunk_blocks(
    blocks: list[ExtractedBlock],
    config: ChunkingConfig | None = None,
) -> list[ChunkNode]:
    """Chunk normalized blocks into a parent/child ``ChunkNode`` tree.

    Dispatches on ``block_type``:
    - ``paragraph``/``page`` → prose strategy
    - ``table``/``sheet`` → tabular strategy
    - everything else (``figure``, …) → singleton child
    """
    config = config or ChunkingConfig()
    nodes: list[ChunkNode] = []
    # Consecutive prose blocks sharing a heading path merge into one section
    # so parents don't fragment per-paragraph.
    prose_section: list[str] = []
    prose_heading: list[str] = []
    prose_meta: dict = {}

    def flush_prose() -> None:
        nonlocal prose_section, prose_heading, prose_meta
        if prose_section:
            nodes.extend(_prose_nodes(prose_section, prose_heading, prose_meta, config))
            prose_section = []
            prose_heading = []
            prose_meta = {}

    for block in blocks:
        if block.block_type in ("paragraph", "page"):
            heading = block.heading_path
            # Merge consecutive same-heading prose, but never across pages —
            # page_number is the citation and must not blur.
            if prose_section and (
                heading != prose_heading or block.page_number != prose_meta.get("page_number")
            ):
                flush_prose()
            prose_section.extend(block.text.split())
            prose_heading = heading
            prose_meta = {
                "page_number": block.page_number,
                "sheet_name": block.sheet_name,
                "source_location": block.source_location,
                "block_type": block.block_type,
            }
            continue
        flush_prose()
        if block.block_type in ("table", "sheet"):
            nodes.extend(_tabular_nodes(block, config))
        else:
            text = _with_heading_prefix(block.heading_path, block.text)
            nodes.append(
                ChunkNode(
                    text=text,
                    heading_path=block.heading_path,
                    token_count=_tokens(text),
                    kind="child",
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                    source_location=block.source_location,
                    block_type=block.block_type,
                )
            )
    flush_prose()
    return nodes
