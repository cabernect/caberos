# Frontend Rework (W13)

**Status: Backlog.** Brainstorming starts after the other v0.2 workstreams land —
pages are still changing under W5/W8/W9, so refactoring now would churn work
in flight. This doc is an inventory and direction note, not a spec.

## Outcome

One consistent frontend: shared page anatomy and primitives instead of
per-page one-offs, semantic surface tokens instead of ad-hoc `--white`/
`--surface` drift, dark mode designed rather than remediated, and page
components small enough to navigate (Conversation is ~2,000 lines).

## Known debt inventory

Evidence gathered during W3/W6 sessions — every item below is a real
instance, not a hypothetical.

### Page anatomy — uneven rework

- **Skills Studio** got the full pass: container-responsive card grid,
  resizable detail drawer, warm-token surfaces, normalized error display,
  consistent hover/border treatment.
- **AgentList / KnowledgeVault / MCPs** got the grid patch
  (`auto-fill + minmax`) but not the rest of the pass — card styling,
  drawer behavior, and empty/error states still diverge.
- **Channels** is untouched — oldest styling generation on the page set.
- **Conversation** works but is a ~2,070-line monolith mixing data fetching,
  SSE handling, composer, preview dock, and heartbeat rendering.

### Repeated patterns not yet abstracted

Each page re-implements these locally; W6 was the third or fourth copy:

- view/filter pill rows (Skills tabs, agent filter selects)
- search row + result-grid pairing
- card grid (now `repeat(auto-fill,minmax(N,1fr))` — pattern proven, copied by hand)
- right-side detail/preview drawers — resize logic now extracted into
  `useResizableWidth` (`src/lib/`), the first shared piece
- modal + confirm dialogs, empty states, scope/status badges
- list/detail split layouts (file list + preview in SettingsOverlay)

### Token and theme drift

- `--white` used where `--surface`/`--sidebar` belonged (docked PreviewPanel
  was pure white against the warm page — fixed ad hoc; audit never ran).
- Hardcoded borders, shadows, and rgba() values scattered outside the token set.
- Dark mode: remediation rules appended to `index.css` reactively during
  W3/W6 — no systematic pass, no designed dark palette for surface roles.

### Responsiveness model

- Viewport-breakpoint grids (`md:`/`lg:`) don't react to drawers or sidebar
  collapse — root cause of the "3 squeezed columns" bug. Fix pattern is
  proven (container-width `auto-fill`); needs applying as a rule, plus a
  decision on whether container queries belong in the stack.
- Wrapped toolbars (pills + search) fixed on Skills; same squeeze pattern
  likely lurks elsewhere.

### Accessibility

- Focus rings, keyboard navigation, and aria on custom widgets are
  piecemeal (resize handles got `role="separator"`; most custom controls
  predate that care).

## Direction (brainstorm seeds)

- **Shared primitives**: `FilterPills`, `SearchRow`, `CardGrid`,
  `DetailDrawer` (built-in resize + close affordance), `EmptyState`,
  `Badge`, `Modal`, `Toolbar` — alongside the existing `PageHeader`.
- **Surface-token audit**: define semantic roles (page / card / dock /
  overlay / accent-soft) and sweep every `bg-[var(--…)]` + hardcoded color.
- **Dark mode as designed state**: first-class token pairs, then a
  page-by-page + modal + preview-renderer audit in dark.
- **Refactor order suggestion**: Conversation (largest, most risk),
  SettingsOverlay, Channels, MCPs, AgentList, KnowledgeVault.
- **Layout strategy decision**: keep `auto-fill` grids vs adopt container
  queries — pick one rule, document it, apply everywhere.
- **Verification**: Playwright screenshot pass over every page in both
  themes as the refactor gate; possibly visual-regression snapshots.

## Explicitly out of scope (for the brainstorm to revisit)

- Design-language changes — this is consistency + structure, not rebrand.
- Component-library adoption (shadcn/Radix/etc.) — decide deliberately,
  not by drift.
- App-level routing/layout redesign.

## Done when (draft — refine in brainstorm)

- Every page renders from the same primitives; no per-page copies of
  pills/search/drawer/grid.
- One documented surface-token model; zero stray `--white` on docked
  surfaces; dark mode passes a full-page audit without remediation CSS.
- No page component over an agreed size budget; resize/preview/filter
  behavior is inherited, not re-implemented.
