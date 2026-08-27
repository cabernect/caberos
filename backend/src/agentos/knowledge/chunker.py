"""Markdown-aware text chunking for local knowledge indexing."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
