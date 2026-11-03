# Integration And Release Gates

Status: proposed. Nothing here authorizes a commit, push, tag, or publication.

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

## Migration And Failure Gates

- Repeated initialization succeeds for SQLite and supported Postgres schema.
- Old managed/custom/ambiguous workspace fixtures keep honest mappings.
- Existing artifact revision bytes and old transcript attachments remain intact.
- Missing directories and providers fail explicitly, not through silent fallback.
- Binding changes, concurrent session creation, active approval waits, and stale
  inspection cursors have deterministic tested outcomes.
- Failed ingestion/publication cleans only newly staged owned files; it does not
  delete preexisting repositories, shared artifacts, or unrelated source content.

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
