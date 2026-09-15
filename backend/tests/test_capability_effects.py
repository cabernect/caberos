"""Tests for capability effect classification (capabilities/effects.py)."""

import pytest

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.effects import (
    DEFAULT_MUTATING,
    effects_from_mcp_annotations,
    is_read_only,
    normalize_effects,
)
from agentos.capabilities.registry import CapabilityDef, registry
from agentos.capabilities.tools.subagent import register_subagent_tools


@pytest.fixture(autouse=True)
def _caps():
    registry._caps.clear()
    register_builtin_capabilities()
    register_subagent_tools()
    yield
    registry._caps.clear()


class TestCapabilityEffects:
    def test_builtin_read_capabilities(self):
        for name in (
            "read_file",
            "search_files",
            "read_terminal",
            "doc_list",
            "doc_search",
            "doc_inspect",
            "web_search",
            "web_fetch",
            "datetime_now",
            "memory_recall",
            "memory_query_facts",
            "search_history",
            "skills_list",
            "skills_load",
            "skills_read_resource",
            "capabilities_search",
            "capabilities_load",
            "read_subagent",
        ):
            cap = registry.get(name)
            assert cap is not None, name
            assert cap.read_only, f"{name} should be read-only, got {cap.effects}"

    def test_builtin_mutating_capabilities(self):
        for name in (
            "write_file",
            "terminal",
            "close_terminal",
            "run_subagent",
            "memory_store",
            "memory_remember_fact",
            "memory_update",
        ):
            cap = registry.get(name)
            assert cap is not None, name
            assert not cap.read_only, f"{name} should be mutating"

    def test_terminal_covers_destructive(self):
        cap = registry.get("terminal")
        assert "destructive" in cap.effects
        assert "external_write" in cap.effects

    def test_normalize_effects_validates(self):
        with pytest.raises(ValueError, match="Unknown capability effects"):
            normalize_effects({"read", "teleport"})

    def test_normalize_effects_empty_is_mutating(self):
        assert normalize_effects(None) == DEFAULT_MUTATING
        assert normalize_effects(set()) == DEFAULT_MUTATING

    def test_is_read_only(self):
        assert is_read_only({"read"})
        assert not is_read_only({"read", "workspace_write"})
        assert not is_read_only(None)

    def test_mcp_annotation_read_only(self):
        effects = effects_from_mcp_annotations({"readOnlyHint": True})
        assert effects == frozenset({"read"})

    def test_mcp_annotation_destructive(self):
        effects = effects_from_mcp_annotations({"destructiveHint": True})
        assert "destructive" in effects
        assert not is_read_only(effects)

    def test_mcp_annotation_missing_defaults_mutating(self):
        # An unannotated MCP tool must never default to read-only.
        assert effects_from_mcp_annotations(None) == DEFAULT_MUTATING
        assert not is_read_only(effects_from_mcp_annotations({}))

    def test_capability_def_normalizes_effects(self):
        cap = CapabilityDef(
            name="t",
            kind="tool",
            description="d",
            parameters_schema={},
            effects={"read"},
        )
        assert cap.effects == frozenset({"read"})

        with pytest.raises(ValueError):
            CapabilityDef(
                name="bad",
                kind="tool",
                description="d",
                parameters_schema={},
                effects={"nonsense"},
            )
