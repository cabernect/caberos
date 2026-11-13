# W0 Decision Requests

Status: all eight decisions approved as recommended, 2026-11-13. Evidence
obligations per row remain outstanding and are tracked in the notes and in
[baseline decision state](w0-baseline-and-decisions.md) §5. Prepared from the
[baseline recommendations](w0-baseline-and-decisions.md) §2, the
[authoring contract](authoring-contract.md) proposals, and the settled
[preview contract](preview-contract.md).

Format: one section per decision — the question, the recommendation, the cost
of each option, and what approval unblocks. Unmarked rows stay visibly open;
"modified" means the row links to the operator's amended decision.

## D1. Spec versioning and authored-spec persistence

**Question.** Do new craft specs declare an explicit version, and do we
persist a normalized authored-spec snapshot per revision?

**Recommendation.** Yes to both. Treat existing unversioned specs as legacy
v1 (today's defaults); require an explicit version on new craft specs and
reject unknown versions. Persist a normalized spec snapshot plus pinned
asset inventory per revision for CaberOS-authored files only — never
reconstruct imported files as if lossless.

| Option | Cost / consequence |
|---|---|
| Approve | Small storage cost per revision (spec JSON << file bytes); one required spec key |
| Version only, no snapshots | Targeted revise cannot diff against authored intent; regeneration and provenance claims weaken; A08/A09 evidence stays fuzzy |
| Defer | Blocks W2/W3 identity work; risks shipping another unversioned surface that must be retrofitted |

**Unblocks:** W2/W3/W3X targeted-revision ops; acceptance A08, A09.

## D2. Stable content addressing

**Question.** How do revise ops identify targets across the three formats?

**Recommendation.** PPTX: `slide_id` plus slide-scoped `shape_id` composite —
a bare shape ID is never valid across slides; index remains the legacy
fallback. DOCX: authored block/section IDs stored as bounded bookmarks —
explicitly *unproven*; must survive an Office open/save round trip before we
rely on it, with revision-bound positional fallback for imported files.
XLSX: sheet name + A1 range scoped to a base revision (already the shipped
model).

| Option | Cost / consequence |
|---|---|
| Approve | DOCX bookmark durability needs a real Word round-trip test; Word is not installed on this machine |
| Positional addressing only | Simple, but duplicate/reorder edits silently re-target content — the failure mode A08 exists to catch |
| Defer | W2/W3 revise-op contracts stay ambiguous |

**Unblocks:** W2/W3 revise-op schemas; A08/A09 correctness evidence.

## D3. Resource budgets

**Question.** What are the hard authoring limits?

**Recommendation.** 100 slides/deck, 100 blocks/slide, 1,000 DOCX blocks,
100k chars/block, 20 MiB packaged assets per file. Validation errors, not
truncation, on violation.

| Option | Cost / consequence |
|---|---|
| Approve | Numbers are judgment calls; easy to relax later, hard to tighten |
| Tighter/looser | Any explicit bound beats an implicit one — pick different numbers and record them |
| Defer | Handlers stay unbounded; hostile/degenerate input cost lands at render time |

**Unblocks:** W2/W3 validation code; A22 bounds evidence.

## D4. HTML deck packaging and isolation

**Question.** Single self-contained file vs pinned bundle, and what runtime
does deck JS get?

**Recommendation.** Single self-contained `.html` — inline CSS/JS, embedded
raster assets, no CDN or remote fonts — plus a platform-owned
navigation/effect runtime (preferred over arbitrary agent-authored JS).
Playback inside `<iframe sandbox="allow-scripts">` with no
`allow-same-origin`; CSP enforced at the serving boundary, not by meta tag
alone. Candidate effect subset: fade/slide transition, one stepwise reveal,
one data-series toggle, reduced-motion + stable capture states.
Bounded execution (a looping deck cannot freeze the app) is a required W2H
proof, not a checkbox here.

| Option | Cost / consequence |
|---|---|
| Approve | Bundle alternative stays available if assets exceed the D3 20 MiB cap; feasibility tests still owed (sandbox, CSP, loop containment) |
| Pinned local bundle | Mutable workspace assets must never change historical playback — pinning discipline becomes the hard part |
| Arbitrary agent JS allowed | Sanitization + isolation burden grows substantially; hostile-script surface widens |
| Defer | W2H has no build target |

**Unblocks:** all of W2H; preview/playback contract for `deck` artifacts.

## D5. Template, effect, and imported-feature matrices

**Question.** Exactly which templates, effects, chart/validation types are
"supported", and what happens to imported files with advanced features?

**Recommendation.** Name the subsets now: one owned 16:9 PPTX master +
bounded layout catalog; fade transition + appear-style reveal (from §2 §D).
One owned DOCX report style set (sections, header/footer, page fields).
XLSX: headered tables + bar/line charts, numeric conditional formats,
whole/decimal/list validation. Imported advanced features (protection,
macros, external links, pivots, drawings, tracked changes): detect at
preflight, warn or refuse destructive edits — never silently strip.

| Option | Cost / consequence |
|---|---|
| Approve | Every matrix row still needs native verification — PowerPoint 16.107 is installed; Word and Excel are absent, so DOCX/XLSX native gates stay blocked on installs or another machine |
| Minimal matrices (fewer features) | Smaller verification surface; agents keep silent gaps the plan promised to close |
| Defer | W2/W3/W3X build unbounded scope; "supported" stays undefined through release |

**Unblocks:** W2/W3/W3X scope boundaries; A01–A05, A20–A22 evidence plans.

## D6. Fonts and capture-runtime policy

**Question.** Which fonts ship/embed, what substitution policy applies, and
does the optional HTML capture path get a managed install?

**Recommendation.** Ship no licensed fonts in v0.2.2; document the
substitution policy (declared font → safe fallback → warning when the
fallback changes metrics). Fixture fonts are already fictional. Treat the
HTML capture runtime as an optional consent-gated managed install — same
model as the managed browser — never an automatic download (invariant 6).

| Option | Cost / consequence |
|---|---|
| Approve | Deck/report typography limited to system + fallback fonts; missing-font fixture evidence already covers the warning path |
| Bundle licensed fonts | License review + redistribution check per font; adds release weight |
| Auto-install capture runtime | Violates the no-silent-authority-expansion invariant — not offered |
| Defer | Font-substitution warnings ship unplanned; capture path undefined for W2H/W5 |

**Unblocks:** W2H playback/capture path; A07 typography evidence.

## D7. XLSX remaining scope and formula calculation

**Question.** Ratify the remaining W3X feature subset, and decide whether
in-app formula evaluation ever enters scope.

**Recommendation.** Ratify the W3X subset in D5 (tables/charts, validation,
conditional formats) plus upload preflight guards and formula-result
provenance (cached values labeled as such, never "recalculated"). Keep
in-app calculation *out* of v0.2.2 — authoring writes real formulas;
evaluation stays a separate later decision requiring a named engine,
function subset, and circular-ref policy. Macros/external links/network
functions are never executed.

| Option | Cost / consequence |
|---|---|
| Approve | Preview keeps showing formula strings + labeled cached values — honest, already implemented |
| Adopt a calc engine now | New managed dependency, function-subset audit, circular/error policy — a release-blocking expansion |
| Defer without ratifying subset | W3X scope drifts; upload guards stay unbuilt |

**Unblocks:** W3X boundary; A21 formula-provenance evidence.

## D8. Quality rubric and reference designs

**Question.** Approve the human review rubric and reference examples per
output type.

**Recommendation.** Rubric axes (already drafted in the acceptance
procedure): readable typography, contrast, whitespace, chart label quality,
data accuracy, pagination, intentional layout. Reference designs: the eight-
slide analysis deck, the styled report, the feature workbook, and one HTML
deck — each reviewed as rendered output, not spec text.

| Option | Cost / consequence |
|---|---|
| Approve | Requires your eyes on rendered output; cannot be delegated — the acceptance matrix assigns design sign-off to the operator |
| Reuse generic "looks fine" review | Rubric stays subjective; W5 inspection loop has no criteria to check against |
| Defer | Downstream lanes lack their quality gate; W6 acceptance stalls |

**Unblocks:** W5 inspection-loop criteria; W6 acceptance.

## Sign-off

| # | Decision | State | Note / amendment |
|---|---|---|---|
| D1 | Spec versioning + persistence | approved (recommended), 2026-11-13 | |
| D2 | Stable content addressing | approved (recommended), 2026-11-13 | DOCX bookmark durability still needs a Word round-trip test — Word not installed on this machine |
| D3 | Resource budgets | approved (recommended), 2026-11-13 | |
| D4 | HTML packaging + isolation | approved (recommended), 2026-11-13 | Bounded-execution + CSP/loop containment proofs remain W2H evidence obligations |
| D5 | Feature matrices | approved (recommended), 2026-11-13 | PPTX native checks possible (PowerPoint 16.107 installed); DOCX/XLSX native gates blocked on Word/Excel installs |
| D6 | Fonts + capture runtime | approved (recommended), 2026-11-13 | No licensed fonts shipped; capture runtime is consent-gated managed install only |
| D7 | XLSX scope + formula calculation | approved (recommended), 2026-11-13 | In-app calculation stays out of v0.2.2; cached values labeled, never "recalculated" |
| D8 | Quality rubric + reference designs | approved (recommended), 2026-11-13 | Rubric axes adopted; rendered-output review of the four reference designs remains operator evidence during implementation |

Approval of a row means the recommendation is adopted; "modified" rows need
a linked note before dependent work proceeds. D2's DOCX bookmark claim, D4's
isolation proofs, and D5's native-edit checks remain *evidence obligations*
even after approval — approval settles scope, not feasibility.
