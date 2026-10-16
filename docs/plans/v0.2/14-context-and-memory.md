# Context and Memory Restructure

Status: implementation ready for review on `feat/v0.2.0-context-memory`.
Request-capture persistence, per-attempt ledger correlation, immutable
conversation-summary snapshots, the trace inspector, and retention controls
are implemented. Focused verification: 304 backend tests green on the touched
suites plus 29-47 narrow reruns after closeout fixes; 184 frontend tests green;
live QA in an isolated environment (backend :18082 + Vite :15174, synthetic
fixtures only) — the earlier full-suite `Page.captureScreenshot` CDP timeout
did not reproduce on isolated retry of the two affected browser tests (both
passed). No full-suite rerun was performed after the final fixes. No production
database migration, deployment, commit, or push has been performed.

## Problem Statement

CaberOS retains conversations but reconstructs the next run from only ten
database records, including tool activity and thinking. Tool-heavy research can
therefore displace the user's original goal and corrections before token
budgeting or compaction occurs.

Memory assembly independently injects a whole notebook, recent KG facts,
matching snippets, and archived-session summaries. These sources overlap and
are not reliable substitutes for the active conversation. Temporary notes,
persistent learning, and core curation have unclear responsibilities.

Compaction does not reliably carry an existing summary into later requests,
has incorrect short-history protection, and can replace failed summarization
with a placeholder. Coverage is not recorded. Normal budget checks exclude
instructions and tool schemas. Manual compaction has a separate loading path.

Traces retain conversation records and usage, not the exact historical request
context. Reconstructing it from today's notebook or retrieval results would be
misleading.

## Solution

Use one context-assembly module to prepare the model input and its inspection
record. It combines platform instructions, a pinned bounded core, coherent
session context, assigned skill metadata, explicitly active procedures, and
currently permitted tool schemas. Apply one input budget before each call.

Keep MEMORY.md as a real, agent-global file for personal-assistant use. Load it
whole: everything admitted to it must be appropriate for the always-loaded core.
Its identity section follows the authoritative versioned soul/persona/task
configuration; curated preferences and standing facts remain file-backed.
Do not inject identity twice or retrieve fragments from this notebook.

Retain detailed knowledge and experiences outside core and reuse existing
memory/history tools for on-demand lookup. Learn clear durable information
automatically, but make core curation a separate inspectable operation. Preserve
source, scope, previous versions, and an undo path. Do not introduce a core
approval gate, a pending-memory queue, or an RSI framework.

Capture each chat-model request attempt at dispatch, with redaction before
storage, explicit completeness, bounded retention, and exact call correlation.

## Commits

These are proposed small work units, not authorization to commit or push.
Each production change includes its regression tests and leaves the application
usable. Activate coherent vertical slices only after their prerequisites pass;
do not expose settings or advertise inspection before their behavior exists.

### 1. Establish regression fixtures and compatibility contracts

Add synthetic Researcher-style conversations with an original goal, corrections,
many tool results, thinking, and subsequent follow-ups. Use scripted models and
isolated databases; never copy private transcripts into committed fixtures.
Measure existing core sizes locally without exposing their text or making model
calls. Select and document default limits from those measurements before adding
enabled settings; do not invent a benchmark or cache-hit guarantee.

### 2. Correct pure compaction behavior

Fix short-history protection and include prior summaries even when no new
compaction is needed. Make failed or empty summarization an explicit unsuccessful
result, not fabricated summary text. Update the test that currently encodes the
wrong short-history boundary and add model-call-level assertions.

### 3. Introduce one conversation loading seam

Reuse stored run ordering and message sequence information, with deterministic
tie-breakers. Exclude thinking and nested sub-agent messages from parent replay.
Retain attachment references and complete tool-call/result groups. Paginate
storage reads without turning page size into a history-retention limit.
Keep legacy ordering uncertainty disclosed rather than inventing chronology.

### 4. Add durable summary coverage

Introduce additive coverage storage and an active-summary reference on the
session. Store the precise original records covered by a summary, its prior
summary reference, and retained head/tail relationships. Publish summary and
coverage together only after successful validation. Uncovered does not mean
simply "newer than a timestamp": protected head records may remain uncovered.

### 5. Integrate continuity across all compaction entry points

Route normal run startup, manual compaction, and overflow recovery through the
same conversation seam and coverage contract. Remove the ten-record selection.
Do not append a dummy user message during manual compaction. Carry only the
summary's uncovered records plus the current message, without duplicating it.
For legacy summaries with unknown coverage, never silently exclude records.

### 6. Centralize complete-request budgeting

Reuse model-catalog input-budget resolution and current compaction settings.
Count platform text, core, history, skills, runtime guidance, and tool schemas;
reserve output once, with a documented estimator safety margin.
Check before every model turn and after dynamic capability loading.
Reduce optional recalled detail before summarizing more conversation.

### 7. Enforce safe compaction failure behavior

On summary failure, preserve original context and continue only if the complete
input still fits the hard budget. Otherwise report a compaction/budget error
without deleting the session. Bound retries; no repeated hidden summarization
loop, placeholder coverage advancement, or silent loss of protected content.
Keep required instructions and the current user message intact.

### 8. Add bounded core revisions and safe file publication

Keep identity authoritative in agent configuration; generate its managed section
in the real notebook. Add core revisions containing exact content, hash,
identity-source version, source references, and publication outcome.
Provide a bounded read/update/restore interface for the actual notebook.
Use per-agent serialization, expected-revision checks, atomic file replacement,
and crash recovery. Never hold a database write transaction over a model call.

### 9. Route every notebook writer through that interface

Cover agent tools, dashboard edits, learning, identity synchronization, restore,
and manual maintenance. Prevent memory edits from changing managed identity.
Count the entire file against a fixed per-agent core token ceiling.
An identity-only overflow is a visible configuration conflict, not permission
to summarize identity. Detect out-of-band file edits rather than blindly
overwriting them; preserve the edited bytes and validate before publication.

### 10. Pin core content for the session

Capture exact validated core content and its identity-source reference once per
session; reuse it across runs and after restart. Add core references to execution
manifests without mislabeling pinned identity as the latest configuration.
New revisions apply to new sessions by default. An explicit refresh is separate
from an ordinary memory write and must be visible.
Current permission enforcement still applies: a stable core cannot pin authority.

### 11. Make learning durable before clearing scratch notes

Process the complete user+assistant transcript — every terminal non-test run
of the session — at session close rather than per run. Persist durable
long-tail entries with agent/contact scope and source references before
clearing temporary notes; the run-scoped direct extraction call remains
unchanged for existing callers. Do not treat quotations, tool instructions,
inferred preferences, or one-off requests as confirmed general rules.
Ambiguity remains explicit. A failed summary or learner attempt leaves the
session open so the next close retries from the same evidence.

### 12. Add core maintenance and remove startup recall injections

Use deterministic duplicate checks and an explicit curation operation.
Trigger model-assisted cleanup when a proposed update exceeds the core ceiling,
or when the operator requests cleanup; not on every turn or application startup.
Protect identity, retain prior versions, and preserve demoted knowledge outside
core. Validate candidates before publication and report cleanup failures.
Remove unconditional KG/snippet/archive searches from assembly while retaining
the existing search capabilities and their permission checks.

### 13. Make on-demand recovery reliable

Keep existing tool names compatible. Ensure durable entries survive successful
learning, and history lookup returns source references and bounded coherent
evidence. Apply agent/contact checks to raw history as well as memory entries;
the current raw-history helper filters only by agent.
Provide recall guidance without restoring automatic startup memory searches.

### 14. Capture each request attempt with exact correlation

Allocate call identity before dispatch and reuse it for capture and accounting.
Cover streaming, non-streaming, sub-agents, compaction, extraction, and other
chat-model calls. Record retries and endpoint fallback as distinct attempts.
Capture rendered context and allowlisted adapter-dispatch input after tool-name
and Responses-format transformations. Exclude credentials and authentication
headers; reuse capability-sensitive redaction before persistence.
Describe the surface honestly: it is not proof of LiteLLM's native wire payload.

### 15. Add bounded capture storage and inspection endpoints

Use short independent transactions so capture failure cannot poison execution.
Expose authenticated call-specific inspection with explicit available, partial,
failed, expired, legacy-not-recorded, and not-applicable states.
Enforce per-payload bounds plus configurable age and installation-wide storage
limits. Remove only expired capture bodies under the enabled retention policy;
preserve trace metadata, receipts, messages, core pins, and summary coverage.
Stop execution on essential persistence failure, not capture failure alone.

### 16. Surface the behavior in Settings and Traces

Add the core ceiling, manual maintenance, and revision/restore information in
the agent Memory settings. Add the capture retention controls in
installation-wide Settings — the policy applies to every agent — never inside
a single agent's overlay. Preserve existing context/compaction settings.
Show pinned core, summary coverage, component token estimates, and capture state
on model-call input views. Label redaction and truncation explicitly.
Keep historical calls honest; never fill missing captures from current state.
Verify desktop/mobile interactions and existing visual patterns in the browser.

### 17. Complete non-destructive migration and final verification

Back up legacy notebook bytes and retain a recoverable long-tail copy before
publishing a curated replacement. Do not delete old messages, KG facts, snippets,
or summaries. Unknown legacy summary coverage remains unknown.
No paid migration/cleanup calls at startup. An oversized legacy core requires
visible editing or explicitly initiated maintenance before it can be pinned.
Update architecture documentation after behavior exists, then run one final
combined verification gate and the synthetic tool-heavy session replay.

## Decision Document

- Context assembly owns coherent input selection, full-input budgeting, and
  inspection metadata; storage pagination never determines retention.
- Persistent memory owns bounded core publication and durable scoped knowledge;
  its interface is shared by all writers, not a wrapper used only by the harness.
- Session core snapshots and conversation coverage are durable, additive schema
  changes. SQLite and Postgres patch contracts must remain compatible.
- Core is agent-global for owner/personal-assistant use. No per-contact notebook
  files or implied safe exposure of that core to unrelated contacts.
- Long-tail retrieval remains subject-scoped and on demand. Lexical lookup
  remains the default; no new embedding dependency or hidden provider egress.
- Automatic learning is not automatic admission to core. Maintenance is a fixed
  memory-management procedure, not recursive self-improvement.
- Core cleanup failures leave the last valid published core unchanged; learned
  information remains retained, and failure is visible. No implicit queue.
- Capture and core APIs preserve existing contracts through additive fields and
  explicit operation results. Authentication, permission ceilings, and approvals
  remain enforced independently from model-visible instructions.
- Selected defaults: 4,096 reference tokens for the whole core; seven days,
  256 MiB installation-wide, and 1 MiB per capture body. The core choice follows
  the offline estimate of seven existing configurations/notebooks (largest
  combined estimate: 1,918 tokens). Capture defaults are bounded-storage policy,
  not measured usage. Measurements are retained locally without notebook text.
  Oversized legacy files require explicit maintenance; no paid startup cleanup.

## Testing Decisions

Test behavior at the interfaces used by callers, using local scripted models and
isolated persistence. Assert the request actually passed to the model/transport,
not merely summary metadata, helper return lengths, or implementation call counts.

Required cases include:

- Tool-heavy follow-ups retain the original task and corrections while they fit;
  when compacted, coverage and the asserted summary represent those records.
- Prior summaries appear exactly once below threshold and with auto-compaction
  disabled; short histories retain all protected content.
- Equal timestamps, multiple runs, parallel tools, attachments, nested sub-agents,
  malformed legacy records, and restart do not silently corrupt replay.
- System/tool tokens trigger the shared budget; output is not reserved twice.
  Dynamic schemas are checked before the next dispatch.
- Failed, empty, or ineffective summaries do not advance coverage; original input
  is used only if it still fits, otherwise no oversized dispatch occurs.
- Core is whole, bounded, identity-preserving, stable across session runs, and
  restored after restart; new sessions see new revisions without duplicate identity.
- All notebook writers enforce the ceiling. Concurrent edits, external changes,
  failed file replacement, and interrupted publication preserve recoverability.
- Clear corrections are durable, scoped, and reversible. Quoted instructions,
  transient results, and failed extraction do not become confirmed core facts
  or cause premature scratch deletion.
- No startup long-tail searches occur; explicit search still works and excludes
  other agents/contacts. Demoted memories remain retrievable.
- Transport doubles prove capture matches each attempted dispatch after redaction,
  including tools, Responses conversion, retries, and streaming.
- Secret canaries and sensitive tool payloads do not survive stored captures or
  API projection. Capture failures leave essential persistence usable.
- Retention expires payloads only; traces show failed/partial/expired/legacy states
  honestly. Wrong-call navigation never displays another call's capture.

Prior art: existing compaction, memory, episodic, pipeline, provider-adapter,
observability-redaction, Settings, and timeline tests. The current narrow baseline
is 82 passing tests; this does not prove the missing continuity behavior.
Add each failing regression with its fixing work unit, then run one final full
backend gate and frontend lint/type-check/build/tests plus browser verification.

## Out of Scope

Tool-payload reduction redesign is a separate follow-up: token-aware per-tool
formatting, new summarizers, and new large-output storage/retrieval mechanisms
are not part of this work. Retain existing tool-specific and harness limits;
complete-request budgeting remains in scope.

RSI workflows, adaptive evaluators, model training, new embedding backends,
Knowledge Vault redesign, cross-agent sharing, per-contact core files, separate
identity Markdown files, provider-cache guarantees, automatic authority expansion,
paid replay of private sessions, daemon restarts, and unrelated local edits.

## Further Notes

Preserve the existing glossary additions and development-script change. Do not
amend independent QA reports. No commits, pushes, GitHub issues, production data
cleanup, or real migration execution without the appropriate user authorization.

Local storage has recovered enough for this small plan, but remains tight.
Use local verification tools, small logs, and isolated test data; do not silently
delete caches or generate large capture artifacts to make space.
