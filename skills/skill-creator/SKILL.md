---
name: skill-creator
description: Draft a CaberOS skill with the operator — use when they want to create a new skill, turn a workflow from this conversation into a skill, or improve an existing one.
license: MIT
compatibility: CaberOS >= 0.2 (Skills Studio builder session)
allowed-tools: agent_ask_user write_file read_file search_files skills_load skills_read_resource run_subagent
---

# Skill Creator

A skill exists to make an agent **predictable**: it takes the same *process* every run, even though its output varies. Every choice below serves that.

You write the draft; the operator reviews and publishes it from the Skills page. Your draft lives in `skill-drafts/<name>/` in your workspace and is inert until published.

## Step 1 — Interview

Mine the conversation first: if the operator says "turn this into a skill", the tools used, the order, and the corrections they made are already the answer. Then ask with `agent_ask_user` (offer options when the choice is closed) until you can state:

- the skill's **job** in one sentence;
- its **branches** — the distinct ways it gets used (e.g. *create* vs *revise*);
- what triggers each branch, in the operator's own words;
- the capabilities it needs — exact names from what this agent can use;
- what "done" looks like for each branch.

To improve an existing skill, read it with `skills_load` (plus `skills_read_resource` for its files) and interview for what should change.

**Done when** you have read those five points back to the operator and they confirmed them.

## Step 2 — Write the draft

Write `skill-drafts/<name>/SKILL.md` with `write_file`.

**Frontmatter** — each value on a single line:

```
---
name: <name>                 # lowercase letters, digits, hyphens; ≤64; equals the folder name
description: <triggers>      # ≤1024 chars
license: <license>
compatibility: <what it needs, e.g. "CaberOS >= 0.2">
allowed-tools: <exact capability names, space-separated>
---
```

**Description** — the agent sees it every turn, so it carries only triggers. Front-load the skill's leading word, write one trigger per branch, and collapse synonyms that rename the same branch.

**Body** — steps and reference:

- A **step** is an ordered action that ends on a checkable **Done when** — the agent can tell done from not-done, and "every X accounted for" beats "produce X".
- **Reference** is rules or facts consulted on demand.
- Inline what every branch needs. Move what only some branches need into a file under `references/` named for its topic, reached by a pointer whose wording says *when* to read it (`skills_read_resource` serves these files to the agent).
- Anchor behaviour with **leading words** — compact concepts the model already knows (*tracer bullet*, *checklist*, *red*). Where three phrases restate one idea, use the word.
- State the target behaviour positively. Keep a prohibition only as a hard guardrail, paired with what to do instead.
- Delete any sentence the model would obey without being told.
- Keep the body under ~3000 words.

**CaberOS limits** — a skill is text the agent reads:

- Reference only capabilities CaberOS has; list each in `allowed-tools`.
- Bundled files are read as text. Scripts, fonts, and images in the skill folder cannot be executed or copied yet — describe the procedure in prose instead.

**Done when** the file exists and every section above is reflected in it.

## Step 3 — Check the draft

Re-read the file with `read_file` and list the folder with `search_files` (`mode: list`). Walk this checklist and report each item to the operator as pass or fixed:

1. `name` equals the folder name and matches the naming rule.
2. Every frontmatter value is on one line; `description` ≤1024 chars.
3. Every file under `references/` that the body points to exists in the folder.
4. Every `allowed-tools` name is an exact capability name.
5. Every step ends on a checkable **Done when**.
6. The body is under ~3000 words.

**Done when** all six pass.

## Step 4 — Dry run (offer it; the operator decides)

A dry run shows whether a fresh agent follows the process. For each of 2–3 realistic prompts, call `run_subagent` with a task that contains the full SKILL.md text followed by the prompt, and `capabilities` set to the skill's `allowed-tools`. Several calls in one turn run in parallel.

Compare each run's process against the steps. Where a run skipped a step or wandered, sharpen that step's **Done when** or its wording, then rerun that prompt.

**Done when** every prompt's run follows the steps, or the operator accepts the remaining deviations.

## Step 5 — Hand off

Tell the operator:

- where the draft is (`skill-drafts/<name>/`);
- to open it on the **Skills** page → **Drafts**, run **Validate**, and **Publish** with the scope they want (agent-local or global).

Publishing is the operator's action; your part ends with a clean draft.
