# Foundations And Decision Gates

Status: proposed. Read `AGENTS.md`, `CONTEXT.md`, and the release plan first.

## Objective

Keep this release additive and local-first. Establish migration and execution
contracts before exposing settings that can change where agent work happens.
Prefer deep modules with small interfaces over per-caller path/policy logic.

## Baseline Facts

- `sandbox/workspace.py` creates a managed directory per agent.
- `pipeline.py` can override that path from agent config; `api/agent_files.py`
  still constructs the managed root for browsing and previews.
- `models/session.py` has no workspace pin. `models/artifact.py` uses an agent
  id as `workspace_id`, so paths cannot safely be reinterpreted after a switch.
- Canonical chunks live in `DocumentChunk`; generations hold derived embeddings
  in `ChunkEmbedding`. Re-embedding is not a historical corpus snapshot.
- `api/chat.py` returns compaction `error`, but the frontend response type and
  handler do not account for it.
- Schema initialization/patches are in both DB backends, not Alembic.
- Search currently has a DDGS implementation; do not assume every tool needs a
  model binding or that configurable search-provider infrastructure exists.

## Decisions Required Before Dependent Code

| Decision | Recommended starting point | Blocked step |
|---|---|---|
| Workspace identity | Stable location record, separate agent authorization | Workspace migration and selection |
| Legacy ambiguity | Backfill only proven roots; explicit repair otherwise | Workspace rollout |
| Atomic switch/admission | One coordinated write path across run producers | Workspace mutation |
| Shared-folder authorization | Per-agent operator grant, not ambient path reuse | Second agent attachment |
| Tabular query bounds | Typed predicates, exact counts, bounded pages | Lifting upload refusal |
| Tools persistence | Reuse persisted-setting rules or a small dedicated table | Binding writes |
| First modality/provider | Image slice implemented; independent operator speech added in W10 | Speech adapter support verification |
| Media accounting/artifact | Typed units and tracked binary output | Media publication |
| Service credentials | Inline Tools setup with encrypted connection references (W9/W10/W11) | Search/speech/remote terminal configuration |
| Speech authority | Authenticated dictation/read-aloud actions, not agent tools (W10) | Operator speech endpoints |
| Terminal execution location | Local-only Auto or explicit pinned local/remote backend (W11) | Sync/background terminal admission |
| Remote workspace/lifecycle | Consented staged copy, conflict-safe retrieval, owned resource leases (W11) | Enabling remote terminal adapters |
| Private-network exceptions | Explicit scoped operator opt-in | Network policy rollout |

Recommendations are not final decisions. Document selected behavior, rejected
alternatives, and compatibility impact in the dependent plan.

## Implementation Steps

1. Inventory workspace constructors/readers, session/run producers, cleanup,
   skill storage, attachment URLs, and artifact ownership. Record the inventory
   in the workspace plan as implementation begins.
2. Add synthetic fixtures: two agents sharing a repository, old/new workspace
   sessions, artifact revisions, long/short conversations, structured documents,
   and multi-sheet tables. Never copy private content into fixtures.
3. Add schema patches with repeated-init and old-schema tests on SQLite;
   maintain Postgres patches and run integration tests where available.
4. Keep new behavior unexposed until its full vertical slice passes. Avoid
   permanent feature flags unless deployment actually needs them.
5. Update `CONTEXT.md` or `TECHNICAL.md` when contracts become implemented facts,
   not while they remain unapproved proposals.

## Compatibility Rules

- No destructive rewrite of legacy paths, transcripts, or revision bytes.
- Invalid external folders fail explicitly, without managed-root fallback.
- Operator-selected host paths are not agent-provided authority.
- No new model/network calls from opening settings or inspecting a document.
- No optional runtime installs or provider probes without explicit consent.
- Preserve unknown cost, unknown coverage, and unknown provenance as unknown.

## Verification

Use isolated databases and temporary directories. Repeated startup must be
idempotent. Verify no production DB, `/Applications` installation, release tag,
or untracked design image changes during planning and development QA.
