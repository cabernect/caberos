# CSV/XLSX Row Retrieval

Status: proposed. Dependencies: bounded row contract and inspection extension.

## Goal

Answer row-oriented questions with complete matching-set counts and accurate
coordinates, not top-k prose snippets pretending to represent an entire table.
Keep tabular uploads refused until this vertical slice passes.

## Existing File Targets

`knowledge/extractors.py`, `knowledge/ingest.py`, `knowledge/retrieval.py`,
`models/document.py`, `api/knowledge.py`, `capabilities/tools/knowledge.py`,
`capabilities/builtin.py`, both DB backends, and the Vault inspection view.
Proposed: a focused `knowledge/tabular.py` module and row/sheet persistence.

## Proposed Storage

- A sheet/table record retains document id, sheet name/index, header mapping,
  dimensions, parser warnings, and corpus version.
- A row record retains sheet identity, original source row number, typed cell
  values, searchable text, and exact coordinate range.
- Preserve original display labels; use stable column ids for querying duplicate,
  blank, or normalized headers. Do not silently merge same-named columns.
- CSV coordinates use a documented synthetic sheet name plus source row/column
  numbering; distinguish that convention from an actual workbook sheet.
- Store source bytes as usual; create derived rows atomically. Failed ingest must
  not publish partial tables or erase an earlier usable document's rows.
- Extend SQLite FTS5 and Postgres search consistently; keep lexical default and
  avoid mandatory embeddings for tables.

Choose final schema and index strategy after representative fixtures. Do not
introduce external databases or a general SQL execution capability.

## Parsing And Limits

Define explicit byte, decompressed-byte, sheet, row, column, cell-text, elapsed
time, and output limits before enabling ingest. Publish tested values and error
messages; do not silently stop parsing and call the document complete.

CSV: bound encoding/dialect detection, handle quoted newlines/BOM, preserve empty
cells and uneven rows with warnings. XLSX: bound ZIP expansion and sparse distant
cells; do not evaluate formulas, fetch external links, or execute macros.
Represent formulas and cached values distinctly; absent/stale caches cannot be
presented as verified computed results. Define handling for hidden sheets/rows,
merged cells, dates/timezones, booleans, blanks, and mixed-type columns.

## Proposed Query Contract

Provide a typed row-query interface exposed through a mediated tool (proposed
`doc_query_rows`) and authenticated inspection endpoints:

- Select document/sheet and projected stable columns.
- Use an allowlisted predicate grammar: equality, comparisons, bounded text
  contains, and explicit conjunctions. No raw SQL or evaluated expressions.
- Define null/type conversion, case sensitivity, numeric precision, and ordering.
- Return exact `matched_count`, bounded rows, stable cursor, corpus version,
  coordinates, and explicit truncation/continuation metadata.
- Support a small allowlisted aggregation set (count/sum/min/max initially),
  evaluated over the full filtered set, not the returned page.
- Bound scan/runtime work too. If an exact result cannot be completed within
  limits, return an explicit incomplete/error outcome, never a guessed total.

`doc_search` can discover tables/rows; the agent must use the row interface for
complete-set questions. Add instructions distinguishing discovery from exhaustive
queries. A large result requires narrowing, deterministic aggregation, or paged
inspection, not unbounded insertion into model context.

## Implementation Steps

1. Specify schema, parser limits, coordinate conventions, predicates, and result
   completeness semantics. Add golden CSV/multi-sheet XLSX fixtures.
2. Implement bounded parsing and atomic row persistence with schema/FTS patches
   and failure cleanup. Keep upload refusal in place externally.
3. Implement filtered paging and exact aggregation with scope enforcement and
   corpus-version cursor checks on both database implementations.
4. Register the mediated query tool and instructions; preserve permission checks.
5. Extend inspection with sheet selection, schema/header warnings, paged rows,
   formula/cache distinctions, and source coordinates.
6. Lift upload refusal only when parsing, querying, citations, and inspection
   all pass. Document supported types, limits, and remaining refusals.

## Acceptance

Test a filter matching more rows than one page: exact total/aggregate must include
all matches. Verify malicious predicate inputs, cross-scope ids, stale cursors,
CSV quirks, formulas, compressed-size limits, parser timeout, failed re-ingest,
duplicate headers, and stable coordinates. Lexical table queries make zero
provider calls; hybrid opt-in retains existing consent/accounting.
