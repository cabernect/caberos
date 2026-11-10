# Integration And Release Gates

Status: proposed. Nothing here authorizes a commit, push, tag, or publication.

This is W12, the final gate after W9 search, W10 speech, W11 terminals, and
their W7 security integration. Earlier CI-equivalent runs are preliminary.
W7 is OPEN: require S01-S10 evidence or explicit feature unavailability;
documented browser/MCP bypasses do not count as completed protection.

## Integrated Acceptance Stories

1. Compact a long conversation while scrolled upward. See pending and estimated
   reduction, reload, and verify persisted coverage. Inject provider failure and
   confirm visible failure without corrupting the saved summary.
2. Attach Developer and Reviewer to one synthetic repository. Both see the same
   files; Reviewer without write capabilities cannot write. Their memories and
   credentials remain separate. No agent-to-agent handoff is implied.
3. Switch Developer's default from repo A to repo B while idle. Old conversation,
   attachments, previews, and artifact restore still use A; a new conversation
   uses B. Switching during admitted work fails atomically.
4. Inspect a prose document's actual parents/children, then a CSV/XLSX sheet's
   rows and coordinates. Query more matches than one page and verify exact count
   and aggregates without flooding model context.
5. Configure the chosen media tool, grant it to one agent, deny an approval, then
   approve a separate request. Only the approved dispatch calls the provider;
   tracked output and modality-aware ledger evidence agree.
6. Attempt blocked private-network destinations and hostile MCP metadata.
   Verify narrow operator-approved local access still works without leaked tokens.
7. Configure Tavily, Exa, and Brave Search API inside Tools, including encrypted
   key entry and explicit synthetic-query tests. Save/reload makes no provider
   calls. Select each scripted adapter; verify normalized results, attempt receipts,
   no paid fallback, and unchanged grants/approval semantics.
8. Configure independent STT and TTS connections in Tools. Record speech into an
   existing draft, edit, and submit normally. Type another message without audio.
   Verify silence, permission denial, cancel, and late results preserve drafts and
   do not leak recording tracks or temporary bytes.
9. Click Read Aloud beside Copy beneath an agent reply containing prose, Markdown,
   code, links, and a table. Verify speech-friendly text, visible skipped-content
   indication, play/stop, scoped audio revision, and replay without another paid
   call. Navigate away during generation/playback and verify cleanup.
10. Switch agents/sessions, change speech/search bindings mid-request, revoke
    credentials, and inspect ledger/audit views. No cross-scope output, secret
    leakage, fake runs/tokens, or falsely free unknown usage. No realtime Voice
    Mode or auto-submit behavior is implied.
11. Select Auto and each supported explicit local terminal backend. Verify the
    actual platform order, unavailable/experimental states, sync/background
    execution, incremental reads, close, and no fallback to open execution.
12. Configure SSH/Daytona/Modal in Tools against isolated/scripted fixtures.
    Authorize a bounded upload, run/read/close a command, retrieve approved
    changes, and detect conflicts without overwriting local edits. Change binding
    during work; the session/resource mapping remains pinned.
13. Disconnect/restart/revoke credentials during remote work. Verify termination
    evidence or explicit orphan/unknown status, owned-resource cleanup and lease
    limits, no hidden paid provisioning/retry, and honest compute/transfer receipts.

## Migration And Failure Gates

- Repeated initialization succeeds for SQLite and supported Postgres schema.
- Old managed/custom/ambiguous workspace fixtures keep honest mappings.
- Existing artifact revision bytes and old transcript attachments remain intact.
- Missing directories and providers fail explicitly, not through silent fallback.
- Binding changes, concurrent session creation, active approval waits, and stale
  inspection cursors have deterministic tested outcomes.
- Failed ingestion/publication cleans only newly staged owned files; it does not
  delete preexisting repositories, shared artifacts, or unrelated source content.
- Tool-connection migration preserves DDGS defaults and image bindings; encrypted
  credentials survive restart and are excluded from plaintext exports/read APIs.
- STT/TTS UI actions do not register agent schemas or bypass message/session
  authorization. Microphone/remote-processing consent and non-run accounting
  receive dedicated regression tests.
- Old terminal/session rows remain local; binding migration never creates remote
  resources. Remote strict mode fails if isolation/network policy cannot be
  enforced. Transfers cannot escape selected roots or overwrite changed files.

## Automated Commands

From `backend/`:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest -q
```

From `frontend/`:

```bash
npm run lint
npm run build
npm run test
```

For desktop changes, from `frontend/src-tauri/`, run `cargo test` and formatting
checks; from `frontend/`, run `npm run desktop:build` on the supported platform.
Record exact commands, environment, commit, and limitations. Postgres-only
integration tests require an isolated configured service; mark unavailable tests
as not run, not passed. Do not install dependencies or use the network silently.

## Browser And Desktop QA

Follow `AGENTS.md` browser tooling requirements. Use isolated QA ports and a
temporary DB/workspace; never replace `backend/data/agentos.db`. Verify wide and
narrow layouts, keyboard/IME behavior, accessible status, and console errors.
Verify actual Tauri microphone permission/recording formats and audio playback,
not only a mocked browser microphone. Unsupported formats/platforms need clear
availability messages; missing native verification is recorded as not run.
Scripted providers cover deterministic failure paths.

Native folder selection, packaged permissions, dragging, quit/reopen, and updater
restart require native evidence. Keep `/Applications` untouched unless explicitly
authorized. Do not infer desktop behavior from browser-only tests.

Real-provider compaction/media QA requires explicit consent for the specific
test's data/egress/cost; earlier conversation consent is not blanket permission.

## Closeout

Record scenarios in `test_result/` with passed/failed/blocked/not-run statuses.
Update `TECHNICAL.md`, `CONTEXT.md`, user docs, and release notes to implemented
facts. Preserve unknown costs and known limitations.

Review scope and all release gates before any version change. Ask before
committing/pushing; rerun CI-equivalent checks before every push. Release tagging,
replacing assets, and destructive cleanup each require their own authorization.
This plan does not move existing tags or choose a release date.
