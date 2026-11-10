# Agent Workspace Selection And Sharing

Status: proposed. Blocking decisions: identity, legacy mapping, run admission.

## Goal And User Stories

- Attach an agent to an existing repository without copying or modifying files.
- Let Developer and Reviewer use the same directory with independent permissions.
- Change an agent's default without making an old conversation act in a new repo.
- Browse, upload, preview, execute, and restore against the same authorized root.

## Existing File Targets

Backend: `sandbox/workspace.py`, `config_schema.py`, `pipeline.py`,
`api/agents.py`, `api/agent_files.py`, `api/knowledge.py`,
`models/session.py`, `models/artifact.py`, `artifacts/service.py`,
`capabilities/tools/subagent.py`, and both `db_backends/*_backend.py` modules.
Audit file/terminal handlers, scheduler, channel session creation, reflection,
skill storage, and agent deletion too; this list is not an exhaustive inventory.

Frontend: `components/SettingsOverlay.tsx`, `pages/Conversation.tsx`,
`lib/api.ts`, workspace/attachment/preview callers, and Tauri chooser permissions.
Do not add unrelated filesystem privileges to enable a folder chooser.

## Proposed Persistent Contract

Use a stable workspace location identity rather than treating agent id as root
identity. A workspace records kind and canonical host path; authorization to use
it belongs to each agent. A session pins that identity, and a run records it in
its execution provenance. Field/table names are to be finalized before migration.

- The agent's default selection is versioned/inspectable with its config.
- Existing sessions never resolve through today's agent default.
- New sessions pin the current authorized default atomically with creation.
- Artifacts bind to the location plus creating-agent provenance. Shared location
  does not automatically merge both agents' artifact registries.
- Attachment URLs carry enough session/workspace identity to find old files.
- Never serialize host paths or cross-agent metadata into an unauthorized view.
- Retain `workspace` config import/export compatibility, but imports may only
  request an external selection, not authorize it silently.

A proposed small workspace interface owns validation, default selection, session
pinning, and effective-root resolution. Callers pass agent/session identities,
not an arbitrary root from the browser. Keep `resolve_within()` for containment.

## Shared Workspace Semantics

- Reusing a canonical directory is allowed, with explicit approval for each agent.
  Do not make filesystem roots globally single-owner.
- Warn that file changes are shared. Identity, memory, secrets, capabilities,
  sessions, and approvals remain separate.
- Temporary sub-agents use the parent run's pin and permission ceiling.
- No automatic file locking, conflict-free collaboration, Git commits, or worktree
  creation. Recommend separate Git worktrees for concurrent overlapping edits.
- A Reviewer can be configured without write/terminal capabilities; sharing a
  directory is not itself read-only enforcement.
- Existing artifact external-edit/conflict checks remain meaningful when another
  agent edits the same file. No silent overwrite on revision/restore.

## Switching And Admission

Reject default changes while the agent has active work, including awaiting
approval and background work that can still access the root. Inventory terminal
and asynchronous sub-agent lifetimes rather than counting running rows alone.

Use one coordinated admission/mutation path. For SQLite and Postgres, choose and
test transaction/locking semantics that prevent switch/start check-then-write
races. An in-process mutex is insufficient if another gateway process is allowed
to write the same store; document supported process topology.

Changing the default affects new sessions only. Persistent channel sessions
remain pinned until explicitly replaced. Old pins remain usable if their
directory is still authorized and available; unavailable roots fail honestly.

## Legacy Migration Gate

1. Inventory default/custom config history, session/run provenance, attachment
   paths, artifact `workspace_id`, skills, and cleanup assumptions.
2. Backfill managed roots only where evidence proves them. Do not infer all
   historical roots from the current config.
3. Where evidence conflicts or is missing, preserve records and require explicit
   operator mapping before path-dependent actions. Read-only chat history remains
   accessible; expose unresolved state and a narrowly scoped repair interface.
4. Preserve immutable revision bytes; map live artifact roots separately.
5. Test upgrade and repeated startup on a copied synthetic old schema, not the
   operator's real database. No automatic external-folder creation or migration.

## Implementation Steps

1. Finalize schema/interface and legacy evidence rules with fixtures.
2. Add additive schema patches for both backends and managed-root compatibility.
3. Route run/session creation and execution through pins, including every trigger.
4. Route file APIs, upload persistence, knowledge-from-workspace ingestion,
   previews, artifacts, and historical links through the same resolver.
5. Implement authenticated validate/select/repair operations; expected invalid
   paths are validation failures, active-work/version races are conflicts.
   Validate again when committing; a prior validation response is not authority.
6. Add Agent Settings managed/existing selection with confirmation. Desktop uses
   native directory selection; web accepts a path on the gateway host; Docker
   explains mounted-path limitations. Show session pin versus new-session default.
7. Audit cleanup and deletion: deleting an agent/selection cannot remove an
   external directory, another agent's files, or shared revision evidence.
8. Run the complete workspace matrix before exposing selection by default.

## Verification

Cover spaces/non-ASCII, symlink aliases/escapes, traversal, root replacement,
missing/read-only directories, disconnected volumes, and restart persistence.
Containment tests must describe any remaining filesystem race limitations; do not
claim hostile concurrent filesystem safety from string canonicalization alone.

Test agent A/B shared roots, independent grants, artifact collisions, agent
deletion, switching with running/approval/background work, all run producers,
old-session uploads/previews/restores, ambiguous migration, and native chooser.

## Non-Goals

No relocation, automatic Git coordination, multiple roots per session,
cross-agent chat/memory sharing, or `/handoff`.
