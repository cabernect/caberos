# W4 spike results — raw CDP adapter

`uv run python ../scripts/spike_browser/run.py [--live]` from `backend/`.
Chromium: cached "Google Chrome for Testing" 145 (Playwright cache — same
binary the managed-runtime installer would pin). Adapter: `adapters.py`,
pure `websockets`, ~200 LOC.

## Measured

| Metric | Local dynamic page | news.ycombinator.com | example.com |
|---|---|---|---|
| Cold open (launch→obs) | ~1.0–2.3 s | 4.2 s | 1.8 s |
| Re-observe | 5 ms | — | — |
| Click / type action | 6–12 ms | — | — |
| Browser RSS (process tree) | ~1.0 GB | ~1.0 GB | ~1.0 GB |
| Initial obs tokens | 74 | **695** | 33 |
| Obs elements | 8 | 81 (80 cap + omission note) | 2 |
| Post-action delta tokens | 10–13 | — | — |
| Extract (30-row table) | 2 ms, correct | — | — |

(First-pass numbers with the loose projection were 973 local / 3853 HN —
structural roles `row`/`cell`/`listitem` were the bloat. Final numbers use
the tightened interactive+landmark projection with an 80-element cap.)

## Verdicts against the plan's budgets

- **Post-action delta ≤800 tokens: holds easily** (10–13). Delta design
  (changed/added/removed lines only) is the right shape.
- **Initial obs ≤2000 tokens: holds after tightening.** Interactive +
  landmark roles only (`button`/`link`/`textbox`/`combobox`/`heading`/
  `navigation`/`main`/`img`/`status`), `MAX_ELEMENTS=80` hard cap with a
  "N elements omitted — observe(scope=…)" marker. HN: 3853 → 695.
  Structural detail (table cells, list items) is reachable via scoped
  observe or `extract`, not the default obs.
- **Latency is dominated by page load, not protocol** — acts are ~6–12 ms
  once loaded; event-driven waits work (`loadEventFired`, no sleeps).
- **Memory is the real footprint**: ~1 GB RSS for Chromium's process tree
  regardless of client. The protocol choice costs nothing; the runtime
  costs everything. Module must enforce idle shutdown + concurrency caps.

## Design findings that change the module

1. **`aria-label` masks text mutations.** First run had
   `aria-label="Increment counter"` on a live counter button — clicks
   produced zero delta because the accessible name never changed. The
   observation must track element *text content* (or value), not just AX
   name, or live-updating labeled elements go silent.
2. **`backendDOMNodeId` refs work** for act (`DOM.resolveNode` →
   `Runtime.callFunctionOn`) — stable enough within a page state, and the
   plan already requires safe invalidation on nav.
3. **websockets-only CDP is sufficient** — target/session attach, AX tree,
   resolveNode, evaluate all work with zero framework. ~200 LOC for the
   spike's core; the module's real cost will be waits/recovery/projection
   policy, not protocol plumbing.
4. **Extraction is trivial** — `Runtime.evaluate` + `returnByValue` handles
   structured pulls; stage large ones as resources per plan.

## What carried into the module

- `DevToolsActivePort` discovery + flatten-session attach pattern
- `Accessibility.getFullAXTree` → role-filtered `Element` list
- Delta-by-line observation shape
- `pgrep` on the profile dir → process-tree RSS for limits
- Local deterministic test page (`page.html`) as the regression fixture

## Not yet proven (next)

- Research-mode resource blocking (Fetch interception) — untested
- Persistent profiles across restarts — untested (spike uses temp dirs)
- Visible/headed mode + takeover — untested
- Cross-origin iframe handling in AX projection — untested
- Multi-tab/session multiplexing on one browser process — untested
