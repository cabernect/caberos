import pytest

from agentos.knowledge.chunker import chunk_markdown


def test_markdown_chunks_preserve_heading_context():
    text = "# Setup\n\nInstall CaberOS.\n\n## Configuration\n\nSet the API key."

    chunks = chunk_markdown(text, max_tokens=8, overlap_tokens=0)

    assert [chunk.heading_path for chunk in chunks] == [
        ["Setup"],
        ["Setup", "Configuration"],
    ]
    assert "Setup" in chunks[0].text
    assert "Configuration" in chunks[1].text


def test_chunks_respect_token_budget_and_overlap():
    text = "one two three four five six seven eight nine ten"

    chunks = chunk_markdown(text, max_tokens=4, overlap_tokens=1)

    assert all(chunk.token_count <= 4 for chunk in chunks)
    assert chunks[0].text.endswith("four")
    assert chunks[1].text.startswith("four")


def test_invalid_chunk_options_are_rejected():
    with pytest.raises(ValueError):
        chunk_markdown("text", max_tokens=0)

    with pytest.raises(ValueError):
        chunk_markdown("text", max_tokens=4, overlap_tokens=4)
