# W7 Test Plan — RAG v2 (hybrid retrieval)

**Audience:** an agent executor. Every case has an exact command + a
machine-checkable assertion. Branch under test: `feat/v0.2-rag` @ `49e4c11`.

**What W7 added:** parent/child `document_chunks` (`kind`, `parent_id`),
per-block-type chunking (prose / tabular / singleton), `embedding_resources`
(egress-gated), `retrieval_profiles`, `index_generations` lifecycle
(rebuild → sweep → validate → atomic activate; rollback; repair; delete),
`chunk_embeddings` float32 BLOBs behind a `search()` adapter seam
(`sqlite-vec` default, pure-Python fallback), `retrieve()` with RRF fusion +
bounded parent expansion + `{document_id, content_hash, coords}` citations +
compact/full trace, `doc_search` switched to `retrieve()`, index-management
API, streamed uploads (250 MB), threaded extraction.

**Fixtures (operator-provided, §0):**
- `big.pdf` — text-bearing PDF, ~500 pages, ideally with bookmarks/outline
- `scanned.pdf` — image-only PDF (no text layer)
- `report.docx` — headings + at least one table + one embedded image
- `data.xlsx` — one sheet, 300+ rows, 5+ columns, real header row
- `vietnamese.md` — Vietnamese-language document
- `mixed.md` — mixed English/Vietnamese (or EN + another language)
- `notes.md` — ordinary multi-section markdown
- `private.md` — short doc for scope-isolation cases

Two agents for scope tests (`$AGENT_A`, `$AGENT_B`). One provider usable for
embeddings — **prefer a local one** (Ollama `nomic-embed-text` or LM Studio)
so the zero-egress path is exercised; a remote provider additionally covers
the egress gate.

---

## 0. Setup

```bash
cd backend
uv run uvicorn agentos.main:app --port 8081 &
# wait for: curl -s http://127.0.0.1:8081/health → {"status":"ok"}

TOKEN=$(curl -s -X POST http://127.0.0.1:8081/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<operator>","password":"<password>"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_token"])')
H="Authorization: Bearer $TOKEN"
API=http://127.0.0.1:8081/api/knowledge

mkdir -p /tmp/rag-fixtures   # drop the fixture files here
```

---

## 1. Baseline lexical — zero config, nothing semantic anywhere

**1.1 Upload + search, no profile/generation/resource configured**

```bash
curl -s -X POST $API/scopes/shared/documents/upload -H "$H" \
  -F "file=@/tmp/rag-fixtures/notes.md"
# → status "indexed", chunk_count > 0

curl -s -X POST $API/scopes/shared/search -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"query":"<a term in notes.md>","include_trace":true}'
```

Assert:
- `results[]` non-empty; each result has `chunk_id`, `content_hash`,
  `matched_text`, `expanded` flag.
- `trace.fusion == "lexical"`, `trace.semantic_hits == 0`,
  `trace.degraded == []`.

**1.2 Index overview before any configuration**

```bash
curl -s $API/index -H "$H"
```

Assert: `profile.config.fusion == "lexical"` (auto-seeded),
`embedding_resource.configured == false`, `active_generation == null`,
`documents.pending == 0` (no generation → `semantic_state='na'`, not pending).

**1.3 `doc_search` in an agent run (compact trace)**

Run an agent (`$AGENT_A`) asking a question answerable only from `notes.md`.
Assert the `doc_search` tool block's result carries `trace` with `fusion`,
`lexical_hits`, `semantic_hits`, `expanded`, `degraded` — and does **not**
carry `normalized_query`/`adapter`/`selected` (those are operator-only).

---

## 2. Chunking structure

**2.1 Parent/child rows + FTS indexes children only**

```bash
# after uploading notes.md / report.docx
uv run sqlite3 <db> "SELECT kind, COUNT(*) FROM document_chunks GROUP BY kind"
uv run sqlite3 <db> "
  SELECT COUNT(*) FROM document_chunks_fts fts
  JOIN document_chunks dc ON dc.id = fts.chunk_id
  WHERE dc.kind = 'parent'"   # → 0
```

Assert: `kind` ∈ {parent, child}; children have `parent_id` set; zero parents
in FTS.

**2.2 Tabular regions — whichever-first split**

```bash
curl -s -X POST $API/scopes/shared/documents/upload -H "$H" \
  -F "file=@/tmp/rag-fixtures/data.xlsx"
uv run sqlite3 <db> "SELECT source_location, token_count FROM document_chunks
  WHERE block_type='sheet' AND kind='parent' ORDER BY seq"
```

Assert: multiple region parents when the sheet exceeds ~450 tok *or* 150
rows; each `source_location` is a real sub-range (`Sheet!A2:E151`,
`Sheet!A152:E301`, …); every child's text starts with the header row; no row
is split mid-row (every non-header line contains `|`).

**2.3 Parent expansion**

```bash
curl -s -X POST $API/scopes/shared/search -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"query":"<term deep inside a long section>", "include_trace": true}'
```

Assert: at least one result with `expanded == true`; `text` is the parent
excerpt (longer than `matched_text`), `chunk_id` resolves to a `child` row;
`trace.expanded >= 1`.

**2.4 Figure singletons** — after uploading `report.docx`:

```bash
uv run sqlite3 <db> "SELECT kind, block_type, parent_id FROM document_chunks
  WHERE block_type='figure'"
```

Assert: `child` rows with `parent_id NULL` — images are retrievable leaves,
never expanded.

---

## 3. Embedding resource + egress gate

**3.1 Remote provider blocked without opt-in**

```bash
PID=<id of a remote provider, e.g. openai>
curl -s -X PUT $API/embedding-resource -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"provider_id\":\"$PID\",\"model_name\":\"text-embedding-3-small\"}"
curl -s -X POST $API/embedding-resource/validate -H "$H"
```

Assert: save succeeds but `provider_local == false`; validate → **403** with
the egress message. No embedding call may leave the machine.

**3.2 Egress opt-in is audited**

```bash
curl -s -X PUT $API/embedding-resource -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"provider_id\":\"$PID\",\"model_name\":\"text-embedding-3-small\",\"egress_allowed\":true}"
curl -s -X POST $API/embedding-resource/validate -H "$H"
curl -s "http://127.0.0.1:8081/api/observability/audit-log" -H "$H" \
  | grep knowledge.embedding_egress_enabled
```

Assert: validate → `status: "ready"`, `dimensions` populated; audit row
exists.

**3.3 Local provider skips the gate**

```bash
PID=<id of ollama/lmstudio provider, base_url localhost>
curl -s -X PUT $API/embedding-resource -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"provider_id\":\"$PID\",\"model_name\":\"nomic-embed-text\"}"
curl -s -X POST $API/embedding-resource/validate -H "$H"
```

Assert: validates `ready` without `egress_allowed`; `provider_local == true`.
(`/validate` response carries the `hint` nudge toward fusion=hybrid.)

**3.4 Dimension mismatch is caught**

Re-point the resource at a model with different dims after a build exists →
probe returns mismatch → `status: "error"`, `last_error` set. (Unit-tested;
manual case optional.)

---

## 4. Enabling hybrid + generation lifecycle

**4.1 First rebuild (bootstrap)**

```bash
curl -s -X PUT $API/retrieval-profile -H "$H" \
  -H 'Content-Type: application/json' -d '{"fusion":"hybrid"}'
curl -s -X POST $API/index/rebuild -H "$H"
```

Assert: response is a generation with `status == "active"`,
`adapter == "sqlite-vec"`, `dimensions` matching the resource, `stats.embedded`
> 0. `GET /index` shows `active_generation` and `documents.pending == 0`.

**4.2 Rebuild semantics — re-embed only, no re-chunk**

Record `SELECT COUNT(*), MAX(seq) FROM document_chunks` before and after a
second rebuild → identical (chunks are canonical; only `chunk_embeddings`
grows with the new `generation_id`).

Assert: `GET /index/generations` shows rev 1 `superseded`, rev 2 `active`;
exactly one active.

**4.3 Rollback sweeps the coverage gap**

```bash
# 1. upload a NEW doc while gen-2 is active → vectors land only in gen-2
# 2. POST /index/generations/<gen1>/activate
```

Assert: gen-1 becomes `active`; the new doc's chunks now have vectors in
gen-1 too (sweep ran); `GET /index` → `documents.pending == 0`.

**4.4 Repair fills a hole**

```bash
# 1. stop the embedding provider (kill ollama / drop network)
# 2. upload a doc → semantic_state becomes "pending" (GET documents shows it)
# 3. restart provider → POST /index/repair
```

Assert: `{"fixed": >0, "still_pending": 0}`; document flips to `embedded`;
search for its content hits.

**4.5 Generation delete is guarded**

Assert: `DELETE /index/generations/<active>` → 404-ish guard; superseded
generation deletes cleanly and its `chunk_embeddings` rows are gone.

---

## 5. Hybrid retrieval quality (the point of the exercise)

**5.1 Synonym recall** — pick a doc that says e.g. "automobile maintenance"
and query `doc_search("car service")` (no shared stems):

```bash
curl -s -X POST $API/scopes/shared/search -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"query":"car service","include_trace":true}'
```

Assert: `trace.semantic_hits > 0` and the doc surfaces — the vector leg found
what BM25 couldn't.

**5.2 Lexical still wins on exact terms** — query a rare literal token;
assert it ranks top via `lexical_hits` and fusion keeps it first.

**5.3 Vietnamese + mixed docs**

```bash
# vietnamese.md + mixed.md uploaded earlier
curl -s -X POST $API/scopes/shared/search -H "$H" \
  -H 'Content-Type: application/json' -d '{"query":"<vietnamese phrase>"}'
```

Assert: hits the right doc via FTS (unicode61); hybrid adds semantic lift on
`mixed.md` when querying the other language's concept.

**5.4 Degradation honesty** — kill the embedding provider, run a hybrid
search:

Assert: results still return (lexical only) and
`trace.degraded` contains `semantic search failed` / `not ready` — the model
must see it in `doc_search`'s compact trace too.

**5.5 adapter fallback** — if `sqlite-vec` can't load (e.g. frozen env):
generation builds with `adapter="python"` and trace reports
`adapter=python` degradation while still returning semantic hits.

---

## 6. Scale + concurrency

**6.1 The 500-page PDF**

```bash
curl -s -X POST $API/scopes/shared/documents/upload -H "$H" \
  -F "file=@/tmp/rag-fixtures/big.pdf" &
sleep 2; curl -s http://127.0.0.1:8081/health   # must answer while ingesting
```

Assert: health responds during ingest (extraction is off the event loop);
doc indexes; per-page citations work — query a term known to be on a late
page → result's `page_number` is correct; `expanded` results carry the page's
parent section.

**6.2 Big upload** — file > 25 MB streams fine (cap now 250 MB); a file >
250 MB returns 413 cleanly and the partial file is removed (`ls` the vault
dir — no orphan).

**6.3 Scanned PDF honesty** — `scanned.pdf` uploads and indexes with 0 (or
near-0) chunks; searches don't crash; `structure.pages` still lists page
count.

**6.4 Re-ingest is idempotent + citation staleness**

```bash
# upload notes.md → note content_hash; edit file; re-ingest
```

Assert: same `document_id`, new `content_hash`; stale chunks replaced
(cascade drops their embeddings); doc goes `pending` or re-embeds if the
resource is healthy. An old citation's hash no longer matches — detectably
stale.

**6.5 Scope isolation at retrieval** — `private.md` into `$AGENT_A`'s scope;
`$AGENT_B`'s `doc_search` for its unique term must not return it (results +
trace checked in the run). Same agent → returns it.

---

## 7. API/UX consistency

- `GET /index` reflects every state transition above (active/building,
  pending count).
- `PUT /retrieval-profile` bumps `revision`; generations snapshot it
  (`profile_revision` differs between rebuilds after an edit).
- Search with `include_trace=false` (default) omits `normalized_query` —
  context-cheap for the model path.

## Known limits (honest)

- Rebuilds are synchronous — a huge vault takes a while; progress is visible
  in `stats_json` on the building generation (`GET /index` polls it).
- python adapter is a fallback path, ~10k-chunk ceiling; production adapter
  is sqlite-vec.
- Chunking-param changes in the profile apply to *future* ingests only —
  re-ingest existing docs to re-chunk (rebuild does not re-chunk).
