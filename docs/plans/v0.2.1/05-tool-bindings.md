# Global Tool Bindings

Status: initial bindings/DDGS/Tavily/image slices implemented and fixture-tested.
Additional search adapters, operator speech, and local/remote terminal configuration
remain pending; see [W9](09-search-services.md),
[W10](10-speech-input-output.md), and [W11](11-terminal-backends.md).

## Goal

Separate platform tool configuration from per-agent authority. Global bindings
choose how a supported tool executes; agent grants decide who may execute it.
The Tools tab is the capability backend registry: each supported tool can have
its implementation swapped — engine options, a keyed service, a model offering,
or an execution backend — without touching per-agent grants. Tools also owns
operator speech configuration; these UI actions are not agent capabilities.

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
references only. Existing model credentials stay in encrypted provider storage;
dedicated service credentials reuse Provider records/encryption with service-type
classification. Configure them inline in Tools; do not add a second secret store.
UI placement never implies plaintext storage.

Search is not inherently model-backed. Keep the current DDGS path usable;
represent its engine configuration separately from Model Offering selection.
Inventory whether any existing search setting needs migration rather than
assuming the roadmap's intended General control is already implemented.

Choose persisted settings versus a dedicated small table before writing code.
Respect existing environment-pinned setting behavior; do not create two competing
authorities. Validate configuration without sending a provider request on save.

## Binding Key Roadmap

The registry grows by adding specs — the table, resolver, mediator freeze, API,
and card UI already generalize. Four binding shapes exist or are planned:

- **engine** — implementation plus validated options, no provider/model
  (implemented: `search.web` ddgs cascade).
- **provider** — keyed service: a Provider record supplies encrypted
  credentials; no model needed (W9: keyed search).
- **model** — provider + model + options (implemented: image).
- **backend** — execution environment selection plus per-backend options
  (W11: local and remote terminal execution).

| Binding key | Shape | Status / notes |
|---|---|---|
| `search.web` | engine or service | DDGS preserved; Tavily inline Provider configuration/dispatch fixture-tested. Exa/Brave API adapters and live verification pending. Firecrawl stays follow-up scope. |
| `exec.terminal` | backend | W11: local-only Auto or explicit supported Seatbelt/Bubblewrap/Docker/MXC; remote SSH/Daytona/Modal with encrypted Tools connections, pinned sessions, consented transfer, verified isolation, and lease cleanup. Remote adapters are not implemented yet. |
| `media.tts` | operator speech service/model | W10: Read Aloud beside Copy beneath agent messages, not the old proposed `media_speak` tool. Provider/model/voice/format configured in Tools. |
| `media.image` | model | Implemented: `image_generate` and `image_edit` share provider/model/options. |
| `media.stt` | operator speech service/model | W10: composer dictation into an editable draft, not an agent tool. Provider/model/language configured in Tools. |
| `media.video` | model | Future; register only alongside a real backend. |

Every new key keeps the same contract: a card shows live selectors only when a
real backend exists — planned entries render an honest note, never a fake
selector. Dedicated service setup stays entirely in Tools, not a new Providers
section. Bindings reference encrypted credentials; secrets never enter plaintext
options or read responses. Remove/replace the unimplemented `media_speak` mapping
when adding the operator TTS path; do not expose it as a loadable schema.

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

The global Tools tab owns working search/image configuration and, as W9/W10 land,
dedicated search and independent STT/TTS connections. Do not present nonfunctional
selectors as supported merely because a model name can be saved. Reuse Model
Offering language for model-backed operations; search APIs are not model offerings.
Do not guess modality support from an alias. Video and realtime Voice Mode stay
deferred; speech UI actions use W10's operator boundary rather than agent grants.

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
