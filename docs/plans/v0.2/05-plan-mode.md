# v0.2.0 Plan Mode

## Outcome

`/plan` lets users inspect and refine a substantial task without side effects, approve a structured revision, and execute it with visible step progress and normal capability gates.

## Interaction

`/plan <goal>` is a built-in run mode, not a Skill or prompt prefix. A composer selector exposes the same mode. Planning remains active across clarification/revision until approve, discard, or exit.

## Domain model

```text
Plan
  id
  session_id
  agent_id
  title
  status
  current_revision_id
  approved_revision_id?
  execution_run_id?

PlanRevision
  objective
  assumptions
  inputs
  expected_artifacts
  required_capabilities
  required_resources
  approval_points
  verification
  risks
  completion_criteria

PlanStep
  order
  title
  description
  required
  status
  outcome?
```

Statuses include draft, awaiting approval, approved, executing, paused, completed, failed, and discarded.

## Planning policy

Syscall mediation permits confidently read-only inspection, retrieval, Skill loading, browser observation, questions, and Plan-draft updates. It blocks workspace writes, terminal execution, memory mutation, artifact creation, browser external writes, mutating MCP tools, Schedule changes, and Skill publication.

Unknown MCP effects default to mutating. Prompt instructions cannot bypass the policy.

## Approval and execution

- User may revise, discard, or approve a revision.
- Approval covers the Plan, not blanket capability calls.
- Execution captures the exact approved revision in its Execution Manifest.
- Harness owns Plan Step status; the model does not waste actions rewriting a todo list.
- Continuous and step-by-step execution are supported.
- Material changes to data scope, authority, persistent profile, outputs, budget, or completion criteria pause and create a new draft revision.
- Tactical adjustments preserving those contracts may continue.
- Revisions never mutate a running execution.

## Staleness and recovery

Before execution, revalidate referenced files/revisions, Skills, Vault snapshots, capabilities, browser grants, and budget. Persist Plan/approval state across restart. Partial failure preserves completed steps and artifacts and supports retry, skip optional step, revise remainder, or stop.

## UI

- Visible Plan Mode badge and mode-specific placeholder
- Structured Plan card with steps, resources, artifacts, gates, verification, and risks
- Revise, Discard, Approve & Execute
- Revision history and comments
- Continuous/step-by-step selection
- Progress timeline linked to calls, evidence, and artifacts
- Material-deviation approval card

## Tests first

- `/plan` never resolves as a Skill
- Read operations allowed and writes blocked at syscall layer
- Revision/approval persistence
- Approval invalidation after edits
- Stale dependency revalidation
- Material versus tactical deviation
- Linked Plan Steps/calls/sources/artifacts
- Partial failure recovery
- Strict sequential reasoning invariant

## Done when

A user can plan the integrated artifact/browser workflow, revise and approve it, execute it, inspect progress, and safely handle a material deviation.
