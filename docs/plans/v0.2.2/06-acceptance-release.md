# W6 - Integrated Acceptance, Documentation, And Release

Status: planned. No release, commit or push is authorized by this document.
Dependencies: required exits from W0-W4 (including W3X); W5 is deferred by
operator decision and is not a release gate. The [acceptance matrix](acceptance-matrix.md)
is the scenario checklist.

## Purpose And Operator Outcome

Prove one complete experience: ask for a deliverable, inspect its exact revision,
request a targeted fix, keep history, download native/portable output and use it
outside CaberOS. Then document actual support and publish through the established
release process only with explicit approval.

Passing source-mode unit tests does not establish native Office editability,
safe HTML playback, or packaged macOS/Windows/Docker readiness.
The [preview contract](preview-contract.md) accepts best-effort uploaded/generated
Office views with limitation alerts. Native Office checks verify authored bytes;
they do not require a faithful in-app engine or disable limited uploaded previews.

## Implementation And Verification Slices

1. **Freeze candidate/evidence scope.** Record integration commit, fixtures,
   environments, runtime/renderer versions, fonts and feature matrices. Map every
   A01-A42 case to a result; record pass/fail/blocked/skipped distinctly.
2. **Workflow acceptance.** Run create/inspect/render/view/revise/restore for each
   format. Include old chat revisions, newer-version banner, external edits,
   uploaded features, retry/degraded modes, cache eviction and restart.
3. **Native Office verification.** In PowerPoint edit text/shape/table/chart data
   and play supported effects; in Word edit styles/body/table and check page
   fields; in Excel edit formulas/table/chart data, recalculate, save/reopen.
   Record versions, OS, fonts and differences from CaberOS previews.
4. **HTML verification.** Open portable output offline in supported browsers;
   test motion, interactions, reduced motion, revision assets and stable captures.
   Run hostile/looping cases separately in browser and packaged Tauri.
5. **Packaging/readiness.** Fresh install and v0.2.1 update on macOS/Windows;
   Docker mounts/runtime/fonts/network controls. Verify partial/failed previews,
   HTML capture runtime states, process cleanup, open/reveal/download and icon.
   Office content previews must work without an Office engine.
   Source-mode success cannot replace unavailable platform evidence.
6. **Bounded diagnostics.** Gateway/renderer smoke tests have deadlines, owned
   process cleanup, and failure logs. Investigate outstanding packaged smoke hangs
   from evidence rather than extending waits or weakening release checks.
7. **Docs and release gate.** Update English and Vietnamese official usage/
   limitations, skill references, README, technical/product docs and changelog.
   Run CI equivalents, request coherent commit/push approval, and separately
   request release approval. Use established manifest/tag procedure; do not retag
   v0.2.1 or hand-edit a stale version.

## Evidence Record Template

Create dated result files when executing checks; do not prefill passing results.

```text
Scenario IDs:
Commit / worktree state:
Fixture / source revision / hash:
Environment: OS, app/browser/Office, renderer, fonts, runtime
Command or manual procedure:
Expected:
Actual:
Status: pass | fail | blocked | skipped
Evidence: logs/screenshots/native edit notes (no secrets/customer data)
Limitations / follow-up:
```

Native editability, static rendering, live playback, formula calculation and
model review need their own evidence even when they use the same fixture.

## CI And Browser Gates

From `backend/`: `uv run ruff check src/ tests/`,
`uv run ruff format --check src/ tests/`, `uv run pytest -q`.
From `frontend/`: `npm run lint`, `npm run test`, `npm run build`.
Run browser verification for changed UI, including keyboard/narrow layout,
revision races and failure states; use isolated QA data/ports.

## Done When

- [ ] All required acceptance scenarios have reproducible results tied to candidate.
- [ ] Native Office and offline/isolated HTML checks complete; blockers not hidden.
- [ ] Supported packaged platforms verified independently.
- [ ] EN/VI docs and skills match implemented capability and limitations.
- [ ] CI/browser gates pass, release notes identify supported subsets and known gaps.
- [ ] Operator approves the release step; publication verified authoritatively afterward.

If a required gate is blocked, retain the blocker or obtain an explicit scope/
support decision. Do not call a skip a pass or announce publication from local tests.
