# Global Tool Bindings

Status: proposed. Dependencies: persistence/readiness decisions.

## Goal

Separate platform tool configuration from per-agent authority. Global bindings
choose how a supported tool executes; agent grants decide who may execute it.

## Existing File Targets

Backend: `api/settings.py`, `config.py`, `providers/interface.py`,
`providers/registry.py`, `providers/model_catalog.py`, `capabilities/catalog.py`,
`capabilities/builtin.py`, and `syscall/mediator.py`.
Frontend: inspect `App.tsx` and global settings routes before choosing the host;
do not put global bindings inside the per-agent `SettingsOverlay.tsx`.
Extend `lib/api.ts` and the existing provider/model selectors where appropriate.

## Binding Model

For model-backed tools, store a capability key, provider id, model name, validated
tool-specific options, revision, and readiness/validation metadata. Store secret
references only; provider credentials stay in the encrypted provider store.

Search is not inherently model-backed. Keep the current DDGS path usable;
represent its engine configuration separately from Model Offering selection.
Inventory whether any existing search setting needs migration rather than
assuming the roadmap's intended General control is already implemented.

Choose persisted settings versus a dedicated small table before writing code.
Respect existing environment-pinned setting behavior; do not create two competing
authorities. Validate configuration without sending a provider request on save.

## Resolution Contract

- Readiness = implemented handler + valid configuration + available provider.
  Capability authorization remains a separate check.
- Unconfigured model-backed tools are absent from loadable schemas. A stale tool
  invocation fails clearly through mediation, not an implicit fallback provider.
- Deleted/disabled providers invalidate bindings; preserve enough information to
  explain and repair them without exposing keys.
- Resolve and freeze the effective binding/options for an admitted invocation,
  including across approval waits. On an incompatible change, fail/re-approve;
  do not approve one destination and silently send to another.
- Configuration edits cannot grant capabilities, disable approvals, or opt into
  egress. Do not probe models or download dependencies automatically.
- Tests and callers use one binding resolver rather than repeating readiness
  conditions throughout catalog, UI, and execution.

## Proposed Operator Interface

Authenticated read/update/reset operations under `/api/settings/tools`, with
typed keys/options, version conflict handling, and safe provider references.
Return configured/available/unavailable reasons separately; never return secrets.
Audit updates using the existing operator-audit mechanism.

The global Tools tab shows functional search and the chosen media configuration.
Future STT/TTS/image/video entries may explain planned support, but cannot present
nonfunctional selectors or claim executable capabilities merely because a model
name can be saved. Reuse Model Offering language and free-text model overrides
where supported; do not guess modality support from an alias.

## Implementation Steps

1. Inventory global settings, provider readiness, search behavior, and catalog
   loading. Decide authoritative storage, validation, and versioning.
2. Implement typed persistence and a small resolver; add restart, invalid-provider,
   pinned-setting, and permission-independence tests.
3. Add authenticated mutation/read interfaces and audit events, without making
   hidden provider calls.
4. Wire catalog/loading plus execution to the resolver; test stale schemas and
   binding changes during approval.
5. Add the global Tools UI with real loading/empty/error/reset states. Preserve
   existing search behavior and migrate any actual persisted settings.
6. Enable the media entry together with its working vertical slice.

## Acceptance

Restart preserves settings; a blank binding does not load a model-backed tool;
adding a binding does not grant authority. Broken references are visible and
repairable. Saving/opening settings makes zero provider calls, secrets remain
redacted, and in-flight calls do not drift onto a newly selected provider.
