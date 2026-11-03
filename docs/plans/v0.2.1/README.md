# v0.2.1 Implementation Plans

Status: planning only. Baseline: `main` at `8b0be89`.
Release scope: [v0.2.1 release plan](../v0.2.1-release-plan.md).

These documents describe proposed implementation, not shipped behavior. File
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
| Gate | [Network and MCP security](07-network-security.md) | Focused threat review | Affected paths have enforced policy |
| Final | [Integration and release](08-integration-and-release.md) | All included workstreams | Evidence-backed release acceptance |

Recommended delivery order is not a requirement to serialize independent work.
Security review starts early, not after media or network changes are finished.
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

## Decisions And Evidence

Record decisions in the relevant workstream before implementing its gated step.
Do not imply that an unchosen provider, legacy path, or concurrency mechanism
has been settled merely because a possible design appears here.

- [Test scenarios](test_plan/acceptance-matrix.md)
- [Test result recording rules](test_result/README.md)

`test_result/` starts without passing results. Previous v0.2.0 evidence is
background only; new changes require new verification.
