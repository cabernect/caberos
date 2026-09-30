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
- Broad reranker ecosystem (no cross-encoder / LLM rerank pass — fusion is RRF only)
- HyDE, GraphRAG, CRAG, and self-RAG
- Knowledge Source / Collection entities beyond the existing shared (`agent_id NULL`) and agent-private scopes — scoping is exercised via those scopes, no new entity layer yet
- Background-task rebuilds — rebuild runs synchronous in-request; progress stats are written to the generation row as it builds so a concurrent `GET` still shows `building` + live counts
- Vault UI for embedding/generation controls — API + response traces first; UI lands with the frontend rework (W13)

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
  → per-block-type chunking (prose | tabular | singleton)
  → parent/child chunks
  → lexical candidates + semantic candidates
  → reciprocal-rank fusion
  → bounded parent-context expansion
  → excerpts + citations + retrieval trace
```

The Vault module hides implementation-specific index behavior from `doc_search` and the harness — `retrieve()` is the sole seam.

## Chunking contract (structured vs unstructured)

`extractors.py` already normalizes every format into `ExtractedBlock`s carrying `block_type` + citation metadata (`heading_path`, `page_number`, `sheet_name`, `source_location`). The chunker dispatches on `block_type` — this is where indexing complexity lives, deliberately contained:

| `block_type` | Emitted by | Strategy |
|---|---|---|
| `paragraph`, `page` | md/txt/docx prose, PDF pages | **Prose**: heading-section parent (~450 tok) → sliding-window children (~120 tok, ~20 tok overlap) |
| `table`, `sheet` | docx tables, xlsx sheets | **Tabular**: region parent (≤~150 rows) → row-group children, each prefixed with the header row |
| `figure` | embedded images | **Singleton**: one child, no parent expansion |

Tabular rules: a row is atomic (never split mid-row); the first row is treated as the header and prepended to every child so rows are self-contained; oversized sheets split into region parents (`Sheet!A1:E150`, `Sheet!A151:E300`, …); children carry row-range `source_location` citations (`Sheet!A5:E12`) instead of the whole-sheet range.

All strategies emit one uniform `ChunkNode` tree (parent + children). FTS indexing, embedding, fusion, and parent-expansion are agnostic to which strategy produced a chunk — a new extractor or block type later adds one strategy, retrieval untouched.

## Schema

New tables (created via `Base.metadata.create_all`; no Alembic yet per D5):

- `embedding_resources` — `provider_id` (FK → `providers`, reuses Fernet key + `base_url` + litellm `{type}/{model}` routing), `model_name`, `dimensions` (null until probed), `status` (`unvalidated|ready|error`), `last_error`, `last_validated_at`
- `retrieval_profiles` — `name`, `revision`, `active`, `config_json` (`fusion: lexical|hybrid`, `parent_tokens`, `child_tokens`, `child_overlap`, `rrf_k`, `max_parents`); editing bumps `revision`
- `index_generations` — `revision`, `profile_revision` snapshot, `embedding_resource_id`, `embedding_model`, `dimensions`, `adapter` (`sqlite-vec|python`, chosen at build), `status` (`building|active|superseded|failed`), `stats_json` (live progress), `error`, `activated_at`; exactly one `active`
- `chunk_embeddings` — `chunk_id` + `generation_id` + `vector` (float32 BLOB) + `dims`; vectors are bound to their generation so incompatible dimensions can never mix

`document_chunks` gains `kind` (`parent|child`; legacy rows = `chunk`) + `parent_id` (self-FK) via `_apply_schema_patches`.

## Modules (`knowledge/`)

- `vectors.py` — float32↔BLOB pack/unpack + two adapters behind `search(query_vec, scoped_chunk_ids, k)`:
  - **`sqlite-vec`** (default) — C-speed exact cosine over `vec0` tables, scales to ~100k+ chunks. Ships via pip wheel (prebuilt binaries).
  - **pure-Python** (fallback) — cosine scan used when the extension can't load; carries `degraded: adapter=python` in the trace (viable to ~10k).
  Adapters are selected at generation build and stored on `index_generations.adapter`.
- `embeddings.py` — `litellm.aembedding` seam; bounded probe embedding to learn dims on save; batched `embed_texts` for indexing.
- `indexing.py` — generation lifecycle: create `building` → embed all retrievable chunks (`kind != 'parent'`) → validate count/dims → atomic activate (previous `active` → `superseded` in one commit) or `failed` with error. Rollback = reactivate a superseded generation.
- `retrieval.py` — the pipeline above; returns excerpts + citations + trace.

`doc_search` swaps `search_documents` → `retrieve()`; result dict keeps every existing key (`chunk_id` stays the *child* id for citation stability, `text` may be parent-expanded) and gains `trace`.

## API surface (extend `api/knowledge.py`)

- `GET /index` — overview: active generation, embedding resource, profile, per-status counts
- `PUT /embedding-resource`, `POST /embedding-resource/validate` — configure + bounded probe
- `POST /index/rebuild` — synchronous build→validate→activate
- `GET /index/generations`, `POST /index/generations/{id}/activate` — list + rollback
- `GET/PUT /retrieval-profile` — fusion mode + chunk params
- `POST /scopes/{scope}/search` gains `include_trace`

## Decisions locked

- **Vector adapter**: `sqlite-vec` default (exact recall, C-speed, ~100k+ chunks) + pure-Python fallback when the extension won't load (trace reports `adapter=python` degradation). Swap surface is the `search()` seam only.
- **Rebuild execution**: synchronous in-request; progress stats committed into the generation row during build
- **FTS-only is a valid profile** — no embedding config required, no error
- **Postgres path**: vector adapter is SQLite-local → lexical-only + degradation note in trace

### Brainstorm decisions (operator-confirmed)

- **Freshness**: embed-at-ingest when the active resource is `ready`; otherwise `semantic_state=pending` (means *pending in the current active generation* — recomputed on activate/rollback/repair). No active gen or lexical profile → `na`.
- **Egress**: remote embedding providers blocked until the operator explicitly enables egress on the resource — gating at configuration time, audited. Local endpoints (ollama/lmstudio/localhost) pass through.
- **Tabular parents**: whichever-first split — close at 150 rows *or* `parent_tokens`, row-atomic; row-range citations cover only rows actually present.
- **Rebuild races**: concurrent build → `409`; building gen sweeps chunks created/changed after build start before validate+activate.
- **Rebuild semantics**: re-embed only — chunks are canonical corpus state; re-chunking requires explicit re-ingest. Generations own embeddings + fusion config.
- **Generation scope**: one global generation; `shared`/`agent` filtering is a query-time predicate.
- **Rollback**: sweep + validate + atomic activate (same invariant as build). Dead resource still flips but reports the pending gap.
- **Repair**: `POST /index/repair` — targeted sweep embedding only chunks missing vectors in the active gen → `{fixed, still_pending, reasons}`. Same sweep code as build-end/rollback.
- **Superseded retention**: keep-all until explicit `DELETE /index/generations/{id}`; rollback never silently dies.
- **Default profile**: seeds `fusion=lexical`; hybrid only turns on by operator action (validate response nudges).
- **Result shape**: `text` = parent excerpt bounded to `parent_tokens`; `chunk_id`/`matched_text` = matched child (citation-stable); `limit` counts matched children; `max_parents` bounds expansion.
- **Citation identity**: `{document_id, content_hash, chunk coords}` — `content_hash` mismatch after edits means the citation is stale, detectably.
- **Trace**: compact in `doc_search` tool result (always carries `degraded[]`); full trace on the API.
- **Token counting**: whitespace-word approximation (zero-dep constraint).
- **Retrieval units**: children only — parents are never FTS-indexed or embedded; they exist solely for expansion.

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
