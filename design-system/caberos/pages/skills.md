# Page: Skills

> **Route:** `/skills`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Capabilities › Skills

Versioned, scoped skill library — "control what each agent knows how to do."

## Anatomy

PageHeader (subtitle = live count, actions: **Import URL** + **New draft**) →
`FilterPills` (views: all / published / drafts / archived) → list rows +
detail panel (same master/detail pattern as MCPs).

## Skill rows

`ListRow`: `IconTile` (tone by status) + name + scope word
(global / agent-name / built-in) + revision `rev N` + status.
Disabled/archived rows render dimmed.

## Detail panel

- Meta: `KeyValueRow`s — status, scope, current revision, activation counts,
  `mono` for ids/paths.
- Revision history: summary + local timestamp.
- Actions by state: **Publish** (drafts), **Disable/Enable**, **Archive**,
  **Duplicate** (`x-copy`), delete draft.
- Assignments: which agents the skill resolves for.

## Publish dialog

Scope radio (Global | Agent-local) + owner `Select` + summary input.
**Revision notice** — warning-tint box when a same-name published row exists
in the target scope: *"…already exists — publishing adds this as revision N+1
of that skill."* Non-draft clashes are rejected (409) server-side.

## Import URL

Modal → archive URL → detected `SKILL.md` dirs → import as drafts (never
publishes; re-importing + publishing = next revision on the same lineage).

## Builder mode

"Create skill" from an agent opens a builder session (`skill-creator`
force-loaded; drafts land in `skill-drafts/`).
