"""Tests for the FTS5 MATCH sanitizer (agentos/fts.py)."""

from agentos.fts import fts5_match_query


class TestFtsSanitizer:
    def test_plain_terms(self):
        assert fts5_match_query("hello world", operator="OR") == '"hello" OR "world"'
        assert fts5_match_query("hello world", operator="AND") == '"hello" AND "world"'

    def test_fts5_syntax_neutralized(self):
        # Column filters, parens, NEAR, asterisks, minus must not survive.
        q = fts5_match_query("email:test@example.com (broken NEAR/3 x) -yolo *")
        assert q is not None
        assert ":" not in q
        assert "(" not in q
        assert "*" not in q
        assert "-" not in q

    def test_quoted_phrase_preserved(self):
        q = fts5_match_query('find "deploy failure" please', operator="AND")
        assert q == '"deploy failure" AND "find" AND "please"'

    def test_empty_or_symbolic_returns_none(self):
        assert fts5_match_query("") is None
        assert fts5_match_query("   ") is None
        assert fts5_match_query(":: -- ()") is None

    def test_dedupes_terms(self):
        assert fts5_match_query("alpha alpha ALPHA", operator="OR") == '"alpha"'
