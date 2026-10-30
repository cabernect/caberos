# CaberOS

Terms used for model offerings, runtime readiness, agent context, and
experience-driven evolution, without confusing proposed improvements with
demonstrated outcomes.

## Language

**Model Offering**:
A model exposed through a particular configured provider, under an exact request
identifier. The same model name through another provider is a different offering.
_Avoid_: Global model identity inferred from a nickname.

**Reported Cost**:
A monetary amount explicitly reported for a model call, distinct from an amount
calculated using a pricing schedule.
_Avoid_: Calling every generated cost estimate an actual charge.

**Estimated Cost**:
A monetary assessment of recorded usage using a specified pricing schedule.
It is not proof of the provider's bill.
_Avoid_: Recovered billing.

**Managed Dependency**:
Optional software whose installation and lifecycle are owned by CaberOS, separate
from software installed and maintained by the operator or operating system.
_Avoid_: System installation.

**Ready Dependency**:
A compatible dependency that supplies the required executables and supporting
resources for a particular capability.
_Avoid_: Downloaded, detected, or installed as synonyms for ready.

**Recursive Self-Improvement**:
In CaberOS, experience-driven revision of an agent's task behavior and the
procedures it uses to develop further improvements. Improvement is evaluated
against evidence, not assumed from a memory update or the agent's own claim.
_Avoid_: Treating ordinary memory accumulation or rewriting the running OS as
equivalent to recursive self-improvement.

**Evolution Workflow**:
A durable, versioned procedure that turns agent experiences into evaluated
proposals for improvement. The procedure itself can be the subject of a proposed
revision.
_Avoid_: Treating a conversation or a skill's prose alone as the workflow.

**Outcome Review**:
Operator feedback on what a run or session produced, delivered as an ordinary
user message in the conversation. It is the evidence input to revision, not a
gate on whether a change may exist.
_Avoid_: Inventing a review artifact that gates agent-local changes, or
treating a verdict about output as a verdict about the procedure that made it.

**Core Memory**:
The bounded, curated information that must accompany every request for an agent:
identity, durable preferences, and a small set of standing facts. A session uses
a stable snapshot of this information.
_Avoid_: Treating all retained knowledge as always-relevant core.

**Long-Tail Memory**:
Retained knowledge and experiences outside the always-loaded core, available
through scoped retrieval when needed.
_Avoid_: Automatically injecting every memory source into each request.

**Core Curation**:
Deliberate selection and maintenance of the information that belongs in core
memory, distinct from learning or retaining a new memory.
_Avoid_: Equating persistence with promotion into core.

**Session Context**:
The working representation of an active conversation: its messages, tool
observations, task state, and any summary of older conversation.
_Avoid_: Equating session continuity with a run-scoped scratchpad.

**Conversation Compaction**:
Lossy compression of part of an active conversation into a summary with explicit
coverage, while retaining original records for recovery.
_Avoid_: Calling silent history omission compaction, or confusing it with core
curation.

**Context Capture**:
A recorded, potentially redacted representation of the input supplied for a
particular model-call attempt, with its capture surface and completeness stated.
_Avoid_: Presenting a reconstruction from current state as an original request,
or equating transport input with proof of the provider's internal processing.
