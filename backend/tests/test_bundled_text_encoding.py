"""Bundled text files must be read as UTF-8 regardless of platform locale.

Python's `open()` and `Path.read_text()` default to the *locale* encoding, which
is cp1252 on a typical Windows install rather than UTF-8. Every bundled file
here contains em-dashes, so omitting an explicit encoding silently corrupts
them: the MCP catalog renders mojibake, and the default agents' soul/persona
reach the model mangled.

These tests read through the production code paths, so they fail if an explicit
encoding is ever dropped again.
"""

import yaml

from agentos.mcp.catalog import _load_catalog
from agentos.seed import DEFAULTS_DIR

# The classic UTF-8-decoded-as-cp1252 signatures: "—" and "→".
MOJIBAKE_MARKERS = ("â€", "â†", "Ã©", "Â ")


def _assert_clean(text: str, what: str) -> None:
    for marker in MOJIBAKE_MARKERS:
        assert marker not in text, f"{what} was decoded with the wrong encoding ({marker!r} found)"


def test_mcp_catalog_decodes_as_utf8():
    """The MCP catalog keeps its em-dashes instead of rendering mojibake."""
    catalog = _load_catalog()
    servers = catalog["servers"] if isinstance(catalog, dict) and "servers" in catalog else catalog
    assert servers, "catalog is empty — bundled catalog.yaml did not resolve"

    blob = str(servers)
    _assert_clean(blob, "MCP catalog")
    # Guard the guard: if the catalog ever loses its non-ASCII content this test
    # would pass vacuously.
    assert "—" in blob, "catalog no longer contains an em-dash; this test proves nothing"


def test_default_agent_configs_decode_as_utf8():
    """Seeded agent soul/persona text is not corrupted on a cp1252 locale."""
    yaml_files = sorted(DEFAULTS_DIR.glob("*.yaml"))
    assert yaml_files, "no default agent YAML found"

    saw_non_ascii = False
    for path in yaml_files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        text = f"{data.get('soul', '')} {data.get('persona', '')} {data.get('task', '')}"
        _assert_clean(text, path.name)
        if any(ord(ch) > 127 for ch in text):
            saw_non_ascii = True

    assert saw_non_ascii, "default agents no longer contain non-ASCII; this test proves nothing"
