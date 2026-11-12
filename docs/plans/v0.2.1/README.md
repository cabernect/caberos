# v0.2.1 Implementation Plans

Status: living release plan; original baseline: `main` at `8b0be89`.
Release scope: [v0.2.1 release plan](../v0.2.1-release-plan.md).

Individual workstreams distinguish implemented slices from pending scope. File
targets refer to existing modules unless explicitly marked proposed. Endpoint,
schema, and helper names are proposals to reconcile with repository conventions.
No commit, push, migration, provider call, or release is authorized by this plan.

## Workstreams

| Order | Plan | Dependencies | Exit condition |
|---|---|---|---|
| 0 | [Foundations](00-foundations.md) | None | Blocking decisions and fixtures identified |
| 1 | [Compaction UX](01-compaction-ux.md) | Existing compaction contract | Honest, session-scoped feedback |
| 2 | [Workspace selection](02-agent-workspaces.md) | Workspace identity/migration decision | Tools and UI resolve the same pinned root |
| 3 | [Vault inspection](03-vault-inspection.md) | Existing canonical chunks | Inspect actual indexed content |
| 4 | [Tabular rows](04-tabular-rows.md) | Row contract; inspection extension | Complete bounded queries with citations |
| 5 | [Tool bindings](05-tool-bindings.md) | Persistence and capability readiness decision | Global bindings survive restart |
| 6 | [First media capability](06-first-media.md) | Tool bindings; provider/artifact decisions | Approved output plus honest ledger |
| 9 | [Search services in Tools](09-search-services.md) | Existing bindings; encrypted tool connections; network policy | DDGS plus Tavily/Exa/Brave API configured entirely in Tools |
| 10 | [Speech input and output](10-speech-input-output.md) | Shared tool connections; audio contracts/accounting | Editable STT dictation and message-level TTS playback |
| 11 | [Local and remote terminals](11-terminal-backends.md) | Tool connections; backend/session pins; transfer and isolation contracts | Local selection plus working SSH/Daytona/Modal execution and lifecycle |
| Gate | [Host protection, network, and MCP security](07-network-security.md) | Starts early; integrates W9-W11 | OPEN: enforced isolation, scoped egress, credential/control-plane separation, and attack-fixture evidence |
| Final | [Integration and release](12-integration-and-release.md) | All included workstreams | Evidence-backed release acceptance |

Recommended delivery order is not a requirement to serialize independent work.
Security review starts early, not after media or network changes are finished.
W7's initial fetch-policy slice is partial, not completion. Final W7 integration
follows W9-W11; W12 release acceptance remains last. Earlier CI runs are
preliminary regression evidence, not final release acceptance.
Each numbered implementation step is a candidate coherent commit, with its own
tests; ask before committing or pushing. Do not land visible dead-end settings.

## Scope Rules

- Preserve the original Vault, tabular, Tools, media, and security commitments.
- Workspace selection supports multiple agents choosing the same directory.
  File sharing does not share memory, credentials, conversations, or authority.
- Existing temporary sub-agents inherit the parent run's pinned workspace.
  Persistent-agent `/handoff` is v0.2.2 or later, not this release.
- Apps/App Studio, npm distribution, workspace relocation, multiple roots per
  session, and broad frontend redesign stay deferred.
- Keep the existing visual language and desktop lifecycle fixes.
- Dedicated search services and STT/TTS are included in v0.2.1, not replaced by
  the implemented image slice. Search/speech credential setup lives in Tools.
- STT/TTS are user actions, not loadable agent tools. Realtime two-way Voice Mode
  with spoken tool instructions is future scope, not record-and-submit dictation.
- Terminal configuration includes both local and remote backends in v0.2.1.
  Auto stays local-only; remote workspace transfer and compute need explicit
  consent, verified isolation, and lifecycle management, not just a selector.

## Decisions And Evidence

Record decisions in the relevant workstream before implementing its gated step.
Do not imply that an unchosen provider, legacy path, or concurrency mechanism
has been settled merely because a possible design appears here.

- [Test scenarios](test_plan/acceptance-matrix.md)
- [Test result recording rules](test_result/README.md)

`test_result/` starts without passing results. Previous v0.2.0 evidence is
background only; new changes require new verification.
