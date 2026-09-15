"""Safe FTS5 MATCH query construction (v0.2 foundations).

FTS5's query language is not natural language: bare input like
`email:test@example.com`, `foo (bar`, or `alpha -beta` is parsed as
column filters, grouping, or boolean operators — producing "no such
column" errors or silently wrong matches.

`fts5_match_query` converts free text into a MATCH expression made only of
double-quoted terms: explicit "quoted phrases" survive intact, everything
else is tokenized into words. A query with no usable terms returns None so
callers can skip the MATCH entirely.
"""

import re

# Explicit "quoted phrases" first, then bare word tokens.
_PHRASE_RE = re.compile(r'"([^"]*)"')
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def fts5_match_query(query: str, *, operator: str = "OR") -> str | None:
    """Build a safe FTS5 MATCH expression from free-text input.

    Args:
        query: Raw user/model input. Never interpolated into SQL unquoted.
        operator: "OR" for recall-style search (any term matches, FTS5 rank
            orders), "AND" for exact-detail search (all terms must match).

    Returns:
        A MATCH expression like `"foo" OR "bar baz"` or None when the
        input yields no searchable terms.
    """
    if not query or not query.strip():
        return None

    parts: list[str] = []
    seen: set[str] = set()

    # Preserve explicit quoted phrases as phrases.
    rest = _PHRASE_RE.sub(" ", query)
    for phrase in _PHRASE_RE.findall(query):
        term = phrase.strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        parts.append(f'"{term.replace(chr(34), chr(34) * 2)}"')

    # Tokenize the remainder into word terms (quotes, parens, colons,
    # asterisks, and other FTS5 syntax characters are dropped).
    for token in _WORD_RE.findall(rest):
        if token.lower() in seen:
            continue
        seen.add(token.lower())
        parts.append(f'"{token}"')

    if not parts:
        return None
    return f" {operator} ".join(parts)
