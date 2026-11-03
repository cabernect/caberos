# v0.2.1 Acceptance Matrix

Status: planned, not executed. Fixtures are synthetic and isolated.
Each row needs a recorded result; add individual regression cases as code lands.

| ID | Scenario | Required evidence |
|---|---|---|
| C01 | Exact command, partial suggestion, Shift+Enter, IME | Composer tests and browser |
| C02 | Pending status visible with scrolled history | Wide/narrow browser captures |
| C03 | Success, no-op, HTTP error, response-body error | Typed response/state tests |
| C04 | Rapid Enter, session switch, late response | No duplicate request or wrong meter |
| C05 | Reload and competing summary writes | Saved coverage and CAS tests |
| W01 | Managed and existing repo, spaces/non-ASCII | Resolver plus filesystem tests |
| W02 | Two agents select same root | Shared bytes, independent grants |
| W03 | Read-only Reviewer, separate memories/secrets | Mediation and identity tests |
| W04 | Default switch and old/new conversations | Stable pins and displayed paths |
| W05 | Switch versus start/approval/background work | Coordinated concurrency tests |
| W06 | Dashboard, channel, schedule, reflection, sub-agent | Same resolution contract |
| W07 | Old attachments/previews/artifact restore | Original authorized location |
| W08 | Traversal, symlinks, missing/denied root | Explicit failure, no fallback |
| W09 | Agent/selection deletion in shared repo | External bytes unchanged |
| W10 | Legacy proven and ambiguous roots, repeated init | Additive migration/repair tests |
| W11 | Native chooser; web host path; Docker mount | Separate supported-host evidence |
| V01 | Parent/child/flat chunks, missing coordinates | Actual persisted values |
| V02 | Paging, re-ingest, stale cursor, scope denial | Coherent corpus, no leaks |
| V03 | Embedding rebuild while inspecting | No fake historical corpus |
| V04 | Empty/error state, document switch | Browser and zero provider calls |
| T01 | Quoted CSV, BOM, uneven rows, duplicate headers | Golden typed rows/coordinates |
| T02 | XLSX sheets/formulas/caches/hidden/merged data | Documented extraction semantics |
| T03 | More matches than one page | Exact full-set count/aggregate |
| T04 | Size/ZIP/time bounds and parse failure | Refusal, no partial active table |
| T05 | Predicate injection, scope, stale cursor | Safe typed query failures |
| T06 | Lexical and opted-in hybrid paths | No hidden provider egress |
| B01 | Binding save/reset/restart, env pin | Authoritative persistence |
| B02 | Missing/deleted provider, stale schema | Unavailable without fallback |
| B03 | Configure but do not grant; pending approval edit | No authority/binding drift |
| B04 | Open settings, preserve search | No hidden probes, working search |
| M01 | Denied versus approved media request | Zero versus one actual attempt |
| M02 | Valid output and playback/download | Tracked revision, scoped access |
| M03 | Invalid/oversize/timeout/cancel/publication failure | Honest status and owned cleanup |
| M04 | Reported/estimated/unknown usage and price | Correct units/provenance/correlation |
| S01 | Private addresses, DNS and redirect variants | Connection-aware policy tests |
| S02 | Browser frames/subrequests/navigation | Actual enforced traffic coverage |
| S03 | Approved local service and exception revocation | Narrow consented access |
| S04 | Hostile MCP discovery/issuer/endpoints/refresh | No credential leakage |
| R01 | Backend/frontend full gates | Exact commands and counts |
| R02 | SQLite and Postgres compatibility | Results or explicit not-run reason |
| R03 | Packaged desktop chooser/lifecycle regression | Native verification |
| R04 | Integrated stories and documentation | No unsupported feature claims |

Use scripted providers for deterministic results. Real-provider tests are optional
consented evidence, never a substitute for failure-path tests. Existing v0.2.0
results cannot be copied as proof that changed v0.2.1 behavior passes.
