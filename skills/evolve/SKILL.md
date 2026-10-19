---
name: evolve
description: Review completed session experience and conversational feedback to maintain reusable agent-local skills without replaying task actions.
license: Apache-2.0
compatibility: CaberOS session-close reflection; inspection and local skill edits only.
allowed-tools: skills_load skills_read_resource skills_usage read_file write_file search_history
---

# Evolve From Experience

Use this procedure during session-close skill reflection. It does not authorize
additional capabilities, external actions, or edits outside agent-local skills.

1. Read the bounded session context. Identify the task outcome, any explicit user
   feedback, and the procedure that might explain the result. A run's success
   status or a skill's activation count is not proof of a good procedure.
2. Separate reusable lessons from one-off execution mistakes, missing information,
   and task-specific exceptions. If no concrete reusable lesson is supported,
   finish without changing a skill.
3. Inspect the relevant existing skill. If no skill fits a reusable method that
   the session actually established, inspect a suitable new skill name instead.
   When summaries omit important details, retrieve relevant original messages or
   tool observations in bounded pages. Never invent missing evidence.
4. Make the smallest useful procedural correction or new skill. Preserve unrelated
   content and resources. Include prerequisites, the reusable steps, and meaningful
   failure checks where supported. Do not embed credentials or private transcript
   copies. A shared or built-in skill must become an agent-local override rather
   than modifying the original.
5. Stage edits with the ordinary `write_file` capability under `skills/{name}/`.
   Inspect an existing procedure with `skills_load` first — it returns the body
   plus a resource listing. Before rewriting any existing file, read its raw
   bytes (`read_file`, or `skills_read_resource` for resources): a staged write
   must contain the complete file — `SKILL.md` needs its YAML frontmatter, and
   any bundled helper file or template needs its full content. Files you do not
   stage are carried
   over unchanged from the inspected version. Inspect a new local name with
   `read_file` before writing it. Finish with a
   short reason tied to this session. The platform validates and conflict-checks
   the staged changes before saving immutable local revisions. A conflict is not
   permission to overwrite newer work. Validation checks structure, not
   improvement in task outcomes.
6. Report only what was actually saved, or why no change was appropriate. The next
   ordinary task provides further evidence; do not replay actions to test the
   revision during reflection.

This procedure may itself receive a focused agent-local revision when experience
supports one. That revision affects later reflections only. It cannot change the
platform's inspection/edit boundaries or cause an immediate reflection loop.
