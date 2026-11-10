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
| Q01 | Tavily/Exa/Brave API setup entirely in Tools | Inline keys/options, no Providers detour |
| Q02 | Key save/replace/remove, restart, export, redaction | Encrypted custody, no read/log/audit secret leaks |
| Q03 | Save/open versus explicit connection test | Zero implicit calls; bounded synthetic probe with consent |
| Q04 | Each API: success/empty/auth/quota/timeout/invalid/oversize | Normalized results, honest failures, no hidden paid retry/fallback |
| Q05 | DDGS migration and official Brave distinction | Original engine order/options preserved; distinct labels |
| Q06 | Grants, pending approval, connection revision/deletion | Same mediation; no admitted destination drift |
| Q07 | Search attempt units/cost and visited-source semantics | Typed service receipts, no fake model tokens/WebSource visits |
| A01 | Independent STT/TTS setup with dedicated and compatible LLM services | Verified per-operation matrix; no fake controls or chat-model change |
| A02 | Dictation: record/stop/transcribe/edit/submit | No auto-send, text-only chat preserved |
| A03 | Microphone denied, silence, unsupported format, bounds | Visible recovery, existing draft preserved, zero denied dispatch |
| A04 | Cancel, navigation, session switch, late result, typing during STT | Tracks/temp bytes cleaned; no wrong-session or draft overwrite |
| A05 | Remote consent, user auth, CSRF, cross-agent/session IDs | Operator boundary enforced; no agent speech schemas |
| A06 | Read Aloud beside Copy before usage; generating/play/stop/error | Desktop/mobile/browser controls; no unsolicited playback |
| A07 | Markdown/link/code/table/raw payload speech rendering | Speakable prose preserved; omitted content disclosed; no hidden LLM rewrite |
| A08 | TTS artifact validation, source pin, auth, revision reuse | Message provenance; no repeat provider call on replay |
| A09 | STT/TTS auth/quota/timeout/cancel/publication failure | Bounded honest failures; no automatic paid retries/fallback |
| A10 | Speech measured/reported/estimated/unknown usage and pricing | Non-run receipts, exact correlation, no fabricated runs or zero-cost claims |
| A11 | Real browser and Tauri microphone/format/playback support | Native evidence or explicit not-run/unsupported status |
| A12 | Voice Mode deferral | No always-listening, realtime turn detection, auto-submit, or voice cloning |
| E01 | Auto and explicit local selection across supported hosts | Actual platform order; no open/remote fallback |
| E02 | Unavailable/experimental backend and missing runtime | Honest readiness, no silent install or privilege escalation |
| E03 | SSH/Daytona/Modal connection save/test and key replacement | Inline Tools setup, encrypted/redacted keys, no implicit provisioning/upload |
| E04 | Admission versus backend edits/revocation | Session/backend/resource pin remains stable or fails explicitly |
| E05 | Sync/background/read/close and cross-run/agent/session access | Driver parity, output cursors/bounds, ownership enforced |
| E06 | Remote upload manifest, exclusions, symlinks, size bounds | Explicit destination/path consent, no identity/credential transfer |
| E07 | Retrieval traversal/archive attacks, conflicts, artifact publication | Contained staged bytes, local edits preserved, exact provenance |
| E08 | SSH host keys/private endpoints, remote strict/network policy | Verified enforcement or clear refusal; no implicit open mode |
| E09 | Disconnect/cancel/timeout/credential loss/restart | Termination evidence or explicit orphan/unknown status |
| E10 | Leases, owned cleanup, cloud idempotency and spend | No unrelated deletion/paid retry; typed receipts, unknown not free |
| E11 | Shell/OS differences and shared workspace sessions | Remote dialect guidance; isolated staging and authorized file sync |
| S01 | Private addresses, DNS, redirects, headers/proxies, body and total-time bounds | Partial: initial 46 policy tests; remaining transport/bounds cases need evidence |
| S02 | Browser frames/workers/subrequests/redirects/WebSockets/popups and direct UDP/proxy bypass | DEFERRED (W7 re-scoped): navigation preflight only; full traffic boundary needs a proxy/OS-level mechanism |
| S03 | Consumer/scheme/host/port/address-scoped local grants; revocation and restart | DEFERRED: baseline keeps exact-host allowlist; scoped grants need a dedicated design, not part of re-scoped W7 |
| S04 | Hostile MCP resource/issuer/endpoints, credential redirects, refresh/reconnect | PARTIAL: PolicyTransport pins all SDK HTTP requests incl. auth flow (synthetic); live SDK-flow verification open |
| S05 | Terminal/MCP worker workspace escape, host secrets/sockets, environment, network and descendants | PARTIAL: Seatbelt confinement verified live on macOS (sibling read+write+symlink denied); bwrap/MXC native runs pending on their platforms; MCP subprocess isolation deferred |
| S06 | Per-operation credential injection; errors/logs/export and redirect leakage | OPEN: dummy-secret isolation and redaction evidence across worker types |
| S07 | Auth, Origin/CSRF/Host checks; localhost rebinding; no worker operator credentials | OPEN: isolated authenticated/unauthenticated control-plane fixtures |
| S08 | CPU/memory/process/output/time/spend bounds, stop, cleanup, recovery copies | OPEN: actual enforcement and termination evidence; unknown remote outcomes explicit |
| S09 | Supported OS/backend readiness, unavailable traffic classes and compatibility | OPEN: tested capability matrix; unsupported paths refused, not labeled strict |
| S10 | W9 search/W10 speech/W11 terminal admission, policy changes and revocation | OPEN: integrated tests after those workstreams; no hidden egress or authority expansion |
| R01 | Backend/frontend full gates after W9-W11 and W7 integration | Preliminary: pytest 1511, vitest 268 in earlier record; final W12 rerun pending |
| R02 | SQLite and Postgres compatibility | ◐ SQLite ran; Postgres not run (no service configured) |
| R03 | Packaged desktop chooser/lifecycle regression | ⊘ Not run — no Tauri/native QA this pass |
| R04 | Integrated stories and documentation | ◐ Docs updated to implemented facts; stories 8–13 cover deferred workstreams |

Use scripted providers for deterministic results. Real-provider tests are optional
consented evidence, never a substitute for failure-path tests. Existing v0.2.0
results cannot be copied as proof that changed v0.2.1 behavior passes.
