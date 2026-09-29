# v0.2.0 Skills Studio

> **Status: IMPLEMENTED** (branch `feat/v0.2-skills`, unmerged). DB-governed
> library with immutable revisions, effective resolution
> (`agent-local > global > built-in`), run-pinned loads, hardened ZIP +
> repo-URL imports landing as drafts, builder-mode sessions, and the React
> Skills Studio. Suite: `test_skills_studio.py` + `test_skills_api.py` +
> updated syscall/preview tests — 694 backend tests pass.

## Outcome

Skills become a visible, versioned, operator-managed library. Users can inspect every global and agent-local Skill and create validated drafts with a dedicated agent before publishing.

## Current gap

The current page lists only system Skills and supports ZIP import/delete. Agent-local Skills are hidden and manipulated through workspace files. ~~The loader intends local-over-system precedence but currently scans system first.~~ **Fixed standalone** (commit `a6b6112`): agent dir scans first, first-wins; `tests/test_skills_loader.py` pins the semantics.

## Architecture

- **Content stays on disk** (Agent Skills spec is file-native; previews and scripts need real paths). The **DB is the resolution index** — the loader resolves the effective per-agent menu from rows (published + assigned + not-disabled), never by raw dir scans.
- Storage per scope:
  - Built-in: `skills/` (shipped read-only), seeded as `scope=built-in` rows at startup
  - Global: `data/skills-store/{skill_id}/rev-{n}/` — immutable dir per published revision
  - Agent-local working copy: `workspace/skills/{agent}/` — live and agent-editable (see below)
  - Agent-owned drafts (builder): `workspace/{agent}/skill-drafts/{name}/`; ownerless operator imports/manual drafts: `data/skills-drafts/{name}/` — **never scanned by the loader**, so drafts are inert until published
- **Built-in vs global split is manifest-driven.** The backend ships a built-in name manifest; a dev test asserts `skills/` ⊆ manifest so it can't drift. Startup migration: dirs in `skills/` not in the manifest (legacy user imports) move to `data/skills-store/` as `scope=global` rev 1. After migration, nothing user-facing ever writes `skills/` again.
- Startup seed computes a content hash per built-in; a changed hash → new `SkillRevision` automatically (source: "app update") — built-ins get history for free.

## Scopes and precedence

```text
agent-local > global > built-in
```

- Built-in: shipped read-only application resources, visible to every agent.
- Global: operator-managed, `availability`: `all` | `selected` — `selected` resolves via `skill_assignments(skill_id, agent_id)`; default `all`. Set at publish/edit time via a multi-select.
- Agent-local: owned by one agent, visible only to it. May shadow a same-named global/built-in; the UI shows "shadows X" explicitly.

Precedence resolves name collisions per agent: each agent's effective menu = its locals + globals visible to it + built-ins, shadowed by name in that order.

## Revisions and pinning

Revision model is minimal — snapshots, nothing more:

- Publish = `copytree` draft/working dir → `data/skills-store/{skill_id}/rev-{n}/` + flip `current_revision_id`. Never overwrite — publish mid-run cannot disturb a live run.
- `Agent-local` working copies stay live/mutable (the self-improvement loop is preserved); "publish local" snapshots the workspace dir into an immutable rev. Pinning for agent-local = recorded **content hash** of the live dir.
- Runs record `skill_pins: {name: revision_id | content_hash}` on the ExecutionManifest (mirrors `artifact_base_revision_ids`) — the loaded menu is pinned at run start; `skills_load` serves the pinned revision.
- History/restore/diff come free from immutability: restore = restore-as-new-revision, diff = rev vs rev.

## Domain model

```text
Skill
  id
  name
  scope               # built-in | global | agent-local
  owner_agent_id?
  availability        # all | selected   (global only)
  status: draft | published | disabled | archived
  current_revision_id

SkillRevision
  id
  skill_id
  revision_number
  storage_path
  content_hash
  source_run_id?
  change_summary
  validation_result   # stored — card renders without re-running
  created_at

skill_assignments (skill_id, agent_id)   # consulted when availability=selected
```

Drafts are `Skill` rows too: "Create Skill" creates `status=draft` with `storage_path` → the workspace draft dir, so the Studio draft panel has an entity from turn zero.

## Skills page

Views: All, Built-in, Global, Agent Skills, Drafts. Support agent filter/search and show scope, owner, revision, resources, capability requirements, assignments, validation, and updated time.

Detail tabs: Overview, Instructions, Resources, Tests, History, Usage. Resources use the shared preview module. Actions include promote, duplicate, export, disable/archive, restore, and safe delete. Shadowing is visible.

## Agent-assisted creation

Create Skill opens a **builder-mode session** on a chosen host agent — not a new agent identity:

1. `skill-creator` (shipped built-in) is force-loaded from turn 0 — the interview methodology lives in the skill, not a bespoke soul. Dogfoods the system.
2. The builder uses **ordinary workspace tools** — drafts live at `workspace/skill-drafts/`, inside the sandbox. No dedicated `skill_draft_*` capabilities exist.
3. Authority boundaries are structural, not promissory: workspace tools cannot reach `skills/` or `data/skills-store/` ("cannot write published storage"), and no publish capability exists ("cannot publish" — publish is an operator-only API).
4. The agent interviews per skill-creator (purpose, triggers, inputs, outputs, capabilities, resources, examples, failure cases) and writes draft files as it goes; validation runs on save.
5. Operator reviews the live draft panel — rendered/raw instructions, resources/scripts, capability requirements, token estimate, validation, diff — then publishes globally, publishes locally, saves the draft, or keeps chatting.

**Testing = publish-local.** Drafts are inert; the scope ladder provides the test lane: publish agent-local (owner only), exercise it in a real session, then promote. The "Tests" tab shows validation history + any `tests/` docs the skill ships — no live-test subsystem.

**Promote** = scope change on the same Skill row (`agent-local → global`) — revision history travels with it. If the agent still wants a private variant afterward, it re-creates a local `foo` (which then shadows, per precedence).

## Installing skills

- **ZIP upload** (existing) — lands as a *draft*, not published directly; review then publish.
- **From repo URL** — paste a Git host URL; the backend fetches the archive zipball over HTTP (no `git` exec), scans it for every directory containing a `SKILL.md` (monorepo repos hold many skills), shows the pick-list, and imports the selection as draft(s). Same hardened import pipeline as ZIP.
- A hosted hub/registry is **deferred** — no settled index standard, and trust/update semantics are their own project.

## Import hardening (both ZIP and URL paths)

- Caps: bounded download stream, total uncompressed size (50 MB), file count (500), single-file cap
- Symlink entries rejected outright; `__MACOSX`/dotfile junk skipped
- Existing traversal/zip-slip and name validation retained
- `https:` URLs only, timeout; SSRF accepted as operator-chosen-URL risk — no private-IP blocking (self-hosted git on a LAN is legit)
- Everything remote lands as drafts — never published

## Authority and validation

- Skills conform to the Agent Skills specification.
- **Errors — block publish:** missing/unparseable SKILL.md frontmatter; `name` invalid or ≠ dir name; `description` missing or >1024; broken resource references; script syntax errors (`bash -n`/`py_compile` where applicable); `allowed-tools` naming capabilities that don't exist; size caps exceeded.
- **Warnings — publish allowed, shown on card:** `allowed-tools` naming real capabilities no assigned agent has (fixable via grants); missing license/compatibility; fat token estimate; empty declared resources.
- Runs at draft-save, on import, and gates publish.
- A Skill never grants capabilities. Scripts execute only through normal mediated tools.

## Delete semantics

- **Archive** — status change only, bytes retained, always allowed (the "off but recoverable" state; `disabled` = listed but not loaded).
- **Purge** — deletes `storage_path` bytes; allowed only when `archived`/`disabled` AND no active run's manifest pins a revision. The dependency-check seam stays open for Plan/Schedule references when those land.
- **Delete draft** — rm the `skill-drafts/` dir + drop the row; no guards (never live).

## Tests first

- All scopes list correctly.
- Local shadows global; global shadows built-in. *(precedence itself already pinned by `test_skills_loader.py`)*
- Assignment bounds global menu exposure.
- App update preserves global/local data; built-in hash change → new revision.
- Builder cannot write published storage; no publish capability exists.
- Invalid references/capabilities block publish; ungranted-capability warns.
- Active run retains pinned revision after a mid-run publish.
- Promotion preserves history and requires review.
- Drafts are inert: never in any menu until published.
- Existing Skill migration loses no content or authority.
- Repo-URL import: archive fetch, multi-SKILL.md pick-list, malicious archives hit the same import hardening, and nothing remote lands published — drafts only.

## Done when

A user can create a Skill through the builder, inspect/test it via publish-local, publish it to selected agents, install one from a repo URL, see local shadowing, and restore a prior revision.

## Explicitly out of scope (v1)

- Hosted skill hub/registry, update channels
- Per-agent disable of built-ins (shadowing covers the real case)
- "Activate draft for one run" — publish-local is the test lane
- Live test-run machinery in the Tests tab
- Per-revision comments, branches, GC policies — snapshots only
