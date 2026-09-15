# v0.2.0 RAG v2 Foundation

## Outcome

Knowledge Vault retrieval becomes reliable, inspectable, and optionally semantic through a separately configured embedding model and one packaged local vector adapter.

## Included

- FTS correctness and query normalization
- Parent/child chunking
- Embedding Resource settings independent from chat model
- SQLite FTS5 baseline
- One local vector-index adapter
- Lexical + semantic candidate fusion
- Index generations, health, repair, and safe re-index
- Vietnamese/English retrieval tests

## Deferred

- OneDrive, SharePoint, Google Drive
- Qdrant/external vector resources
- SQL Knowledge Sources
- Broad reranker ecosystem
- HyDE, GraphRAG, CRAG, and self-RAG

## Concepts

- Knowledge Source: origin of documents
- Knowledge Collection: agent-assignable corpus
- Embedding Resource: provider/model producing vectors
- Index Adapter: lexical/vector storage and search
- Retrieval Profile: revisioned chunking/index/fusion/limit composition
- Index Generation: immutable derived index activated after validation

## Retrieval pipeline

```text
structured parsing
  → parent/child chunks
  → lexical candidates + semantic candidates
  → reciprocal-rank fusion
  → bounded parent-context expansion
  → excerpts + citations + retrieval trace
```

The Vault module hides implementation-specific index behavior from `doc_search` and the harness.

## Embedding settings

Store provider, model, vector dimensions, privacy/egress state, health, and safe configuration. Validate with a bounded test embedding before indexing. FTS-only remains a valid profile and requires no embedding model.

Changing model/dimensions creates a new Index Generation. Keep the old generation active during rebuild; never mix incompatible vectors. Derived indexes remain rebuildable from source documents.

## Degraded behavior

- Embedding unavailable: existing vectors remain usable where safe; changed documents show semantic indexing pending; FTS continues.
- Vector adapter unavailable: fall back to FTS when profile permits and report degradation.
- Partial document failure is visible by parsing/lexical/embedding/vector states.
- Empty retrieval returns structured empty evidence and never encourages fabrication.

## Observability

Trace query normalization, lexical/semantic candidate counts, fusion rank, selected chunks, parent expansion, warnings, and context-token cost without leaking unrelated document text.

## Tests first

- Punctuation/hyphens cannot become FTS column errors.
- Parent/child retrieval preserves precise citation and useful context.
- Cross-agent/collection isolation across both paths.
- Embedding validation and dimension mismatch.
- Atomic generation activation/rollback.
- Honest vector-failure fallback.
- Partial indexing health/repair.
- Stable citation revision identity.
- Vietnamese/English/mixed-language queries.
- Frozen gateway loads local vector adapter.

## Done when

An existing Vault can opt into local hybrid retrieval, inspect why sources ranked, rebuild safely after model change, and continue with FTS when semantic infrastructure is unavailable.
