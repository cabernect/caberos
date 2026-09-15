# v0.2.0 Foundations and Reliability

## Outcome

CaberOS has the shared provenance, authority, revision, and packaging foundations required by every v0.2.0 pillar. Known defects are fixed before new modules depend on them.

## Included

- Execution Manifest captured at run start
- Capability effect classification
- Shared immutable-revision conventions
- Per-model-call accounting foundation
- Packaging risk spikes
- Known runtime and release regressions

## Deferred

- Remote/Docker per-agent execution environments
- CaberCore extraction
- Generic executable plugin SDK

## Invariants

- A conversation remains `reason → act → observe → repeat`, one reasoning step at a time.
- FastAPI remains a gateway layer.
- Skills and Plans never widen capability authority.
- A running execution uses captured revisions; later edits affect future runs.
- Secrets, cookies, and private content are not copied into provenance metadata.

## Execution Manifest

```text
ExecutionManifest
  run_id
  agent_config_revision
  plan_revision_id?
  schedule_revision_id?
  skill_revision_ids[]
  retrieval_profile_revision_id?
  knowledge_snapshot_ids[]
  browser_profile_id?
  artifact_base_revision_ids[]
  created_at
```

The manifest stores IDs, versions, and safe hashes. It is immutable after execution starts.

## Capability effects

Add a trusted effect classification independent from `egress` and approval:

```text
read
workspace_write
local_execute
external_write
destructive
```

Built-ins declare effects. MCP annotations inform classification, but unknown/untrusted MCP tools default to mutating. Operator overrides are explicit and audited.

## Shared revision convention

Plans, Skills, Artifacts, Schedules, and Retrieval Profiles use immutable revisions:

- a stable logical identity points to a current revision;
- edits create a new revision;
- restore creates another revision instead of rewriting history;
- active runs retain their captured revision;
- deletion distinguishes archive/tombstone from permanent purge.

## Risk spikes

Complete before dependent implementation:

1. Generate and render representative DOCX/PPTX/XLSX/PDF files on a clean macOS ARM64 machine.
2. Prove the Office/PDF renderer packaging or managed-runtime strategy.
3. Select and prove the browser automation engine/protocol and compatible first-use runtime installer.
4. Prove the same browser runtime in Docker.
5. Package the selected local vector adapter in the frozen gateway.
6. Verify all managed resources survive Tauri update without unnecessary re-download or data loss.

## Known defects

- Merge the OpenRouter duplicate-thinking fix.
- Keep `web_fetch` trafilatura data and BeautifulSoup fallback in packaged builds.
- Repair natural-language FTS queries that become missing-column errors.
- Repair restricted sub-agent protocol imports in packaged builds.
- Retry/clean transient `hdiutil: Resource busy` failures.
- Distinguish denied, failed, timed-out, and interrupted tool results.
- Verify a release tag points to the intended commit before publishing.
- Set the default model stream idle timeout to 60 seconds while preserving its environment override.

## Tests first

- Execution Manifest captures exact revisions without secrets.
- Capability effects cannot be changed by model arguments or Skills.
- Existing v0.1.9 data migrates idempotently and can be restored.
- Each known defect has a focused regression test.
- Desktop and Docker packaging spikes run on clean environments.
- Release verification rejects a mismatched tag/version/commit.

## Done when

Every downstream pillar can depend on stable revision, effect, provenance, and packaging contracts, and all listed regressions pass in source and packaged runtime tests.
