# Page: Traces + Run detail

> **Routes:** `/traces`, `/traces/:agentId`, run detail `/traces` → run
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Observability › Traces (› Run `id8` in detail)

## List view

PageHeader → KPI `StatCard`s (runs, tokens, cost, last run) → filter row:
`FilterPills` status + quick-date chips (**today** = local midnight, 7d, 30d)
+ trigger/model `Select`s + free-text since/until → run table → footer.

- **Failure-cluster banner:** when ≥3 same-trigger failures cluster in one
  **local** day with <10min gaps — dismissible, resurfaces when the cluster
  shifts.
- **Run rows:** status word, trigger, agent, model (mono), tokens in/out,
  cost, latency, `fmtStarted` = `Oct 6 · 9:19 AM` local. Error column shows
  truncated `danger` mono.
- Click → run detail. `exportRunsXlsx` downloads filtered set.

## Run detail

PageHeader `Run {id8}` + breadcrumbs back → stat cards (tokens in/out, cost,
latency, context breakdown `n / max`) → `TraceInspector`.

## TraceInspector

Tabbed: **Syscalls** (`RunSyscalls` — audit-derived timeline, fmtTime local,
latency ms, call_id mono) · **Messages** (`RunMessages` — role + local time,
latency) · **Timeline** (`RunTimeline` — audit roots → tool_call tombstones →
pending approvals; unknown timestamps stay unpositioned). Context re-projection
via `/api/model-calls/{id}/context` opens redacted bodies.
