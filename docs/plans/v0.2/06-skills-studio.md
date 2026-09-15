# v0.2.0 Skills Studio

## Outcome

Skills become a visible, versioned, operator-managed library. Users can inspect every global and agent-local Skill and create validated drafts with a dedicated agent before publishing.

## Current gap

The current page lists only system Skills and supports ZIP import/delete. Agent-local Skills are hidden and manipulated through workspace files. The loader intends local-over-system precedence but currently scans system first.

## Scopes and precedence

```text
agent-local > assigned global > built-in
```

- Built-in: shipped read-only application resources.
- Global: operator-managed application data, available to all or selected agents.
- Agent-local: owned by one agent and may explicitly shadow another scope.

User global Skills must be stored separately from replaceable built-in resources.

## Domain model

```text
Skill
  id
  name
  scope
  owner_agent_id?
  availability
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
  validation_result
  created_at
```

Runs pin loaded revisions. Publish affects future runs only.

## Skills page

Views: All, Built-in, Global, Agent Skills, Drafts. Support agent filter/search and show scope, owner, revision, resources, capability requirements, assignments, validation, and updated time.

Detail tabs: Overview, Instructions, Resources, Tests, History, Usage. Resources use the shared preview module. Actions include promote, duplicate, export, disable/archive, restore, and safe delete. Shadowing is visible.

## Agent-assisted creation

Create Skill launches a dedicated Skill Builder with authority limited to draft storage. It asks about purpose, triggers, inputs, outputs, required capabilities, approval-sensitive behavior, resources, examples, and failure cases.

Operator reviews rendered/raw instructions, resources/scripts, egress/capabilities, token estimate, validation, tests, and diff, then publishes globally, publishes locally, saves draft, or continues editing. The builder cannot publish directly.

## Authority and validation

- Skills conform to the Agent Skills specification.
- Name/directory, resource references, capability names, compatibility, size, and script syntax are validated.
- A Skill never grants capabilities.
- Scripts execute only through normal mediated tools.
- Imports prevent traversal, symlink escape, archive bombs, and destructive replacement.
- Active Plan/Schedule dependencies block purge; archive remains available.

## Tests first

- All scopes list correctly.
- Local shadows global; global shadows built-in.
- Assignment bounds global menu exposure.
- App update preserves global/local data.
- Builder cannot write published storage.
- Invalid references/capabilities block publish.
- Active run retains pinned revision.
- Promotion preserves history and requires review.
- Existing Skill migration loses no content or authority.

## Done when

A user can create a Skill through the builder, inspect/test it, publish it to selected agents, see local shadowing, and restore a prior revision.
