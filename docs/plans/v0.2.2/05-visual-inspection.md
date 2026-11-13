# W5 - Agent Visual Inspection And Bounded Revision

Status: planned; no visual-review capability is claimed from fixture inspection.
Dependencies: [W1](01-rendering-foundation.md), relevant authoring lanes and
[W2H](02h-html-presentations.md) capture; [W4](04-preview-experience.md) integrates operator requests.

## Purpose And Example Workflow

Agent creates a deliverable, inspects structure, views images of the exact
revision, spots a crowded slide/table, revises the identified object, then checks
the new revision before delivery. Operator can see what was actually reviewed.

Structural validity, render success, model visual review and operator approval
are separate outcomes. Seeing a screenshot cannot establish formula correctness,
PPTX effect playback or HTML animation behavior.
The [preview contract](preview-contract.md) allows approximate Office content
views for uploaded and generated files. Carry their limitations into model review.
Reviewing extracted/reflowed content does not verify exported Office layout; if
only that view is available, report native-layout review as unavailable. A screenshot
of a spec/design representation is labeled as such, never a native-render claim.

## Proposed Workflow

```text
plan content/design -> create revision -> inspect structure
  -> request bounded render/capture -> view selected images
  -> record issues/coverage -> targeted revise -> inspect new revision
  -> re-render/review changed output -> deliver with remaining limitations
```

A non-vision model, unavailable renderer, or exhausted run budget stops visual
review honestly. No automatic model/provider upgrade or terminal workaround.

## Implementation Slices

1. **Capability seam.** Extend the existing artifact boundary with the minimal
   approved render/read interface. All agent requests cross syscall mediation
   and authorized exact-revision resolution. Reuse W1 instead of subprocess
   recipes in agent terminal calls.
2. **Bounded image input.** Return dimensions, source/revision/page identities,
   warnings and limited image references through existing supported image-input
   handling. Honor decode/pixel/count/context budgets; no unrestricted server
   paths, unauthenticated URLs or unbounded base64 history.
3. **Evidence model.** Specify storage for review coverage, renderer/version,
   reviewed revision/hash, pages/ranges, run/model-call attribution, issues,
   outcome and limitations. Use exact identifiers, never temporal joins.
4. **Skill procedure.** Teach structure-first checks, visual rubric, focused
   corrections and reinspection. For large outputs select bounded batches and
   report unreviewed pages/ranges; do not claim whole-artifact approval.
5. **Iteration control.** Set explicit review iteration/image/render budgets
   within existing turn/context/cost limits. Stop on repeated failure or no
   progress; preserve the last valid revision and state remaining issues.
6. **Revision invalidation.** A fix creates new bytes/revision; previous review
   cannot become a pass for the new revision. Recheck changed output and
   record any reuse of unchanged coverage explicitly rather than silently.
7. **Cross-format checks.** PPTX/DOCX page images, HTML stable states and bounded
   XLSX range/chart views use consistent provenance. Add formula/reference checks
   separately; live playback tests remain distinct from captures.

## Failure And Authority Rules

Rendering/model errors remain traceable, with actionable partial results.
Prompt instructions in uploaded documents/decks never expand permissions.
Missing vision support is "visual review unavailable", not a visual pass.
Normal model-call ledger/capture/redaction behavior applies; real-provider tests
require explicit consent with expected cost and egress.

## Tests And Completion

Acceptance: A23-A25 plus A08-A10, A16, A20-A22, A33 and A42 where relevant.
Use scripted tests to inject a layout issue and verify request/revise/review
identities; scripted success alone is not visual quality evidence.

- [ ] Authorized exact-revision images reach an admitted vision-capable model.
- [ ] A controlled issue is corrected once and the new revision is rechecked.
- [ ] Partial coverage, non-vision, render failure and exhausted limits report honestly.
- [ ] Review attribution remains correct after revision switch/restore.
- [ ] Consented real-provider demonstration and human review evidence recorded.

Targets: artifact capability implementation/registration/schema, harness image
results only as needed, revision/review provenance, Office/presentation skills,
and scripted plus opt-in integration tests.
