# W7 Test Results — RAG v2 (hybrid retrieval)

**Run:** 2026-10-01  
**Branch / tested code:** `feat/v0.2-rag` @ `49e4c11`  
**Environment:** macOS; backend `127.0.0.1:8081` (uvicorn); embedding provider OpenAI (`a4da6653`) `text-embedding-3-small` with `egress_allowed` opt-in; **no local embedding provider available** (no Ollama/LM Studio) — §3.3 blocked. Auth via a temporary minted operator session (login credentials unavailable; session revoked during cleanup).  
**Fixtures:** operator-provided `data/` → `/tmp/rag-fixtures` (`notes.md`, `report.docx`=sample-simple.docx, `data.xlsx`=08 E-Commerce Orders.xlsx 1001×12, `big.pdf`=war-peace.pdf 2043pp, `scanned.pdf`=PublicWaterMassMailing.pdf 8pp image-only, `vietnamese.md`, `mixed.md`, `private.md`, plus synthesized `auto.md`, `bigfile.md` 31.9 MB, `huge.pdf` 260 MB).

## Verdict

**PASSING after fix verification.** Retrieval quality, generation lifecycle, scope isolation (agent level), and scale all pass. The run surfaced five real defects (B23–B27) plus one cross-cutting defect (B28); **all six were independently re-verified as fixed on the uncommitted follow-up diff** — see "Fix re-verification (2026-10-01)" below.

## Results by case

| Case | Result | Evidence |
|---|---|---|
| 1.1 upload + lexical search, no config | PASS | `notes.md` → `b2eb6ba7`, `indexed`, 6 chunks, hash `9604cee8…`. Query "tokenizer Vietnamese" → 1 result, all fields present (`chunk_id`/`content_hash`/`matched_text`/`expanded`); trace `fusion=lexical`, `semantic_hits=0`, `degraded=[]`. |
| 1.2 index overview pre-config | PASS | `profile.config.fusion="lexical"` rev 1 auto-seeded; `embedding_resource.configured=false`; `active_generation=null`; `documents.pending=0` (pre-generation docs are `semantic_state='na'`). |
| 1.3 `doc_search` compact trace | PASS | `caber` run `00ee7069` (session `68de5af9`): query "tokenizer" → notes.md found; tool result trace keys exactly `{fusion, lexical_hits, semantic_hits, expanded, degraded}` — no `normalized_query`/`adapter`/`selected`. (First attempt's over-long AND query returned nothing — test-input issue, not a defect.) |
| 2.1 parent/child + FTS | PASS w/ note | W7 docs: `kind ∈ {parent, child}` (legacy `kind='chunk'` rows belong to pre-W7 docs only). `parents in FTS = 0`. Region children have `parent_id` set. **Note:** standalone children of sections under `parent_tokens` and singleton leaves carry `parent_id NULL` — intended per chunker (`parent` rows exist only to bound expansion) and explicitly sanctioned by §2.4 for figures. |
| 2.2 tabular regions | PASS | `data.xlsx` → `644cbdc0`: 67 `parent` regions with real sub-ranges (`E-Commerce Orders!A2:L16` … `A992:L1001`, ~15 rows/region, token bound hit first); 334 children, **all** start with the header row; 0 non-header lines missing `\|` (no mid-row splits). |
| 2.3 parent expansion | PASS | Query "institutions of state and church are erected" → result `expanded=true`, `text` 2103 chars > `matched_text` 694, `chunk_id`→child row, `page_number=2042`, heading `["Second Epilogue","Chapter XII"]`; `trace.expanded=5`. |
| 2.4 figure singletons | PASS | `report.docx` → `62c6a084`: figure row is `kind=child, parent_id NULL` (retrievable leaf, never expanded). |
| 3.1 remote blocked w/o opt-in | PASS | PUT resource (OpenAI, no egress) → `provider_local=false`; validate → **403** "Remote embedding requires egress_allowed — vault text would leave this machine". |
| 3.2 opt-in audited | PASS | PUT `egress_allowed:true` → validate `status=ready`, `dimensions=1536`; audit row `knowledge.embedding_egress_enabled` visible via `GET /api/operator-audit`. |
| 3.3 local provider skips gate | **BLOCKED** | No local provider on this machine (no Ollama/LM Studio) — zero-egress path not exercised live. |
| 3.4 dimension mismatch | PASS (unit) | `tests/test_knowledge_rag.py::test_dimension_mismatch_probe` — suite green (23/23). Plan marks manual case optional. |
| 4.1 first rebuild | PASS w/ defect | Gen `98408e82` rev1 → `active`, `adapter=sqlite-vec`, `dimensions=1536`, 6959 vectors, `pending=0`. **But** concurrent rebuilds/uploads 503'd and `building` state never visible → **B23**. |
| 4.2 re-embed only | PASS | `document_chunks` count+max(seq) unchanged by rebuilds (+1 only for a doc uploaded mid-test). Gens 2→3 rotated `superseded`/`active`; exactly one active at all times. |
| 4.3 rollback sweeps gap | PASS | `rollback-doc.md` `72031250` ingested under gen3 → vector only in gen3; `POST …/generations/<gen1>/activate` → gen1 active, sweep backfilled the doc's vector into gen1, `pending=0`. |
| 4.4 repair fills hole | PASS | Resource broken (bogus model → `unvalidated`) → `repair-doc.md` `a7a35c52` went `pending`, `/index` pending=1; resource restored → `POST /index/repair` → `{fixed:1, still_pending:0}`, doc `embedded`, content searchable. |
| 4.5 generation delete guarded | PASS | `DELETE` active gen1 → 404 "still active"; `DELETE` superseded gen2 → 204, its 6959 `chunk_embeddings` rows gone. |
| 5.1 synonym recall | PASS | "car service" → `auto.md` ("automobile maintenance", no shared stems) surfaced at rank 2 via `semantic_hits=50`, `fusion=hybrid`. |
| 5.2 lexical wins on literal | PASS | "ORD-10001 Betty Miller" → top-5 all `data.xlsx` rows. |
| 5.3 Vietnamese + mixed | PASS | "nước dùng phở Hà Nội" → top-3 all `vietnamese.md` (unicode61 FTS). English "flexibility commute" → top-3 all `mixed.md`; VN phrase hit mixed.md too. |
| 5.4 degradation honesty | PASS | With resource `unvalidated`: results still returned (lexical 28 hits on "tokenizer") + `trace.degraded=["embedding resource not ready; lexical only"]`; same message visible in `doc_search` compact trace (runs `e8f004fd`, `77a6b2d5`). |
| 5.5 adapter fallback | PASS (unit) | `test_adapter_python_fallback_reports_degradation` green; sqlite-vec loads here so live fallback path not exercised. |
| 6.1 big.pdf (2043pp) | PASS | Indexed 8236 chunks with real outline sections; `/health` answered in 39 ms mid-ingest and 39–78 ms mid-large-write; late-page query hit `page_number=2042` correctly with expanded parent section. |
| 6.2 >25 MB streams; >250 MB → 413 | PASS w/ defect | `bigfile.md` 31.9 MB → `indexed`, 53167 chunks (resource was unvalidated → `pending`, no embed storm). `huge.pdf` 260 MB → **413** in 2.6 s, partial file removed. **But** two earlier raced bigfile attempts + scanned.pdf attempts left 4 orphan vault files → **B26**; and the writes-blocked window → **B23**. |
| 6.3 scanned PDF honesty | **FAIL** | `scanned.pdf` → **500** `StatementError: bind parameter 'content'` — zero-chunk docs crash `_write_chunk_nodes` (empty executemany). → **B25**. |
| 6.4 re-ingest idempotent | PASS | notes.md edited → same `document_id` `b2eb6ba7`, new `content_hash` `c191df36…`, all 6 old chunk ids + their 12 embedding rows cascade-dropped, 7 new chunks, `semantic_state=pending` (resource down) — old citations detectably stale by hash. |
| 6.5 scope isolation at retrieval | PASS (agent) / **FAIL** (operator preview) | `private.md` `0b3b2712` → `caber` scope. `test-agent` run `e8f004fd`: `doc_search("Blue Heron")` → 0 results → answered NOT FOUND. `caber` run `77a6b2d5`: found `private.md` (count=1). **But** operator `scope=shared` search also returns it → **B27**. |
| 7 /index reflects transitions | PARTIAL | `active`/`superseded`/`pending` all correct; **building state never visible** (uncommitted row) → part of **B23**. |
| 7 profile revision snapshot | PASS | PUT `rrf_k=70` → profile rev 3; rebuild → gen4 `750171f9` `profile_revision=3` vs gens 1&3 `profile_revision=2`. |
| 7 include_trace=false | PASS | trace present but compact — `{fusion,lexical_hits,semantic_hits,expanded,degraded}` only; no `normalized_query`. |
| `test_knowledge_rag.py` suite | PASS | 23/23 (16.8s). |

## Defects filed

| # | Summary | Status |
|---|---|---|
| B23 | Rebuild + large ingest hold one uncommitted write txn for their whole duration → global `503 database_busy` blackout for all other writes, `building` state invisible to `/index` (progress unobservable), `RebuildInProgress` 409 guard defeated (concurrent rebuild gets 503), dead-client ingest keeps writing (WAL grew to ~300 MB). | FIXED — re-verified live |
| B24 | `embed_chunks_at_ingest`/`repair` overwrite `generation.stats_json` with the single batch — gen1 showed `{embedded:1,total:1}` while holding 6961 vectors. | FIXED — re-verified live |
| B25 | Zero-chunk ingest → 500 `bind parameter 'content'` (empty executemany); scanned/image-only PDFs cannot index at all. | FIXED — re-verified live |
| B26 | Ingest failures other than `ValueError/UnicodeError` leave orphaned vault files (6 orphans observed incl. 2×31.9 MB). | FIXED — re-verified live |
| B27 | Operator `scope=shared` search/preview returns agent-private documents (`agent_id IS NULL` param = unscoped). Agent-level isolation verified correct. | FIXED — re-verified live |
| B28 | `awaiting_approval` excluded from backend `active_run` filter and frontend `recoverableSessions` — parked approval runs unreachable after navigating away. (Surfaced during the fix-review pass.) | FIXED — re-verified live |

## Notable correct behaviors worth calling out

- **Egess gate is real:** validate 403 without opt-in, opt-in audited in `operator_audit_logs`, local-provider flag computed honestly (`provider_local:false` for OpenAI).
- **Degradation is honest end-to-end:** broken resource → `degraded` note in both operator full trace and agent compact trace; lexical leg keeps answering.
- **Rollback sweep works:** activating an old generation backfills coverage gaps for docs ingested meanwhile.
- **Canonical chunks:** rebuilds never re-chunk or duplicate `document_chunks`.
- **Atomic activation + guarded deletion:** exactly one active generation; active delete refused; superseded delete cascades embeddings.

## Environment notes / not-run

- §3.3 local zero-egress path — blocked (no local embedding provider installed).
- §5.5 python-adapter live fallback — sqlite-vec loads in this env; covered by unit test only.
- One over-long AND query on `doc_search` (§1.3 first attempt) returned no hits — reclassified as a test-input artifact, not a defect; shorter query passed.
- Backend restart mid-run was required to break B23's write lockout (forced kill; WAL rolled back cleanly, `integrity_check` ok).

## Fix re-verification (2026-10-01)

The coding agent's fix diff (uncommitted, on top of `49e4c11`) was re-tested live against a restarted backend on :8081 — not taken on trust. Regression suite: **30/30** `test_knowledge_rag.py` (+7 fix-regressions incl. `test_stale_building_generation_reconciled_on_startup`).

| Bug | Live re-verification evidence |
|---|---|
| B23 | During a 6,958-chunk rebuild: `GET /index` shows `building_generation` with **live stats** (`768/6958` mid-flight); concurrent `POST /index/rebuild` → **409** (was 503); concurrent doc upload → **200 in 6.1s** (was instant-503 blackout); build completed `6958/6958` → `active`. *In-handler failure:* provider `encrypted_key` corrupted mid-build → `decrypt()` `InvalidToken` escapes the per-batch catch → gen `a09e51f4` committed `status=failed` with partial stats `256/6612` + 500 to caller. *Crash path:* `kill -9` mid-build → restart → `reconcile_stale_builds` flipped committed `building` row `67402cb6` → `failed` ("Gateway restarted during build", startup log confirmed); next rebuild accepted immediately. |
| B24 | After rebuild (`stats 6958/6958`), a 1-chunk ingest moved stats to `6959/6959` — accumulated, not reset. |
| B25 | `scanned.pdf` (same fixture) → 200 `indexed`, `chunk_count=0`, `structure.pages=[1..8]`. |
| B26 | `corrupt.pdf` (random bytes → extraction error) → 500, vault file count **10→10** (no orphan), zero doc rows. |
| B27 | `private.md` under `caber` scope: `scopes/shared/search "Blue Heron"` → `[]`; `caber` → `[private.md]`; `test-agent` → `[]`. |
| B28 | Run `c5273cd3` → `awaiting_approval`: session list reports `active_run_status=awaiting_approval`; SSE replay re-emits `tool_call` `pending_approval` + `approval_id`. **Browser E2E (Playwright :5173):** approval card rendered → navigated to /agents → deep-linked back via `?session=` → **card re-rendered** with live Approve/Deny → Deny clicked → approval `rejected`, run `f58ae168` completed. |

**Post-retest cleanup:** 10 test docs API-deleted (chunks/embeddings/vault files cascaded); 3 generations + embedding resource cleared; profile restored to `lexical`; 2 test sessions + 2 runs + messages/approvals removed; minted token revoked (401); DB vacuumed + `integrity_check` ok; backend healthy.
