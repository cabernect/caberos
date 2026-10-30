# Page: Overview (Observability)

> **Route:** `/observability`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Observability › Overview

"How your agents have been doing." Read model over the `model_calls` ledger +
run history — reported vs estimated cost stays honest.

## Anatomy

PageHeader (+ ⌘K, actions: export ↓) → `FilterPills` day windows
(1d / 7d / 30d / 90d — `?tz=` sends operator zone) → stat cards →
time-series bars → per-agent table → recent runs → spend detail.

## Stat cards

`grid-cols-2 lg:grid-cols-4`: Total runs, Total cost, Total tokens, Error
rate, Avg latency — `StatCard` (caption → 24/30 value → sublabel).

## Time series

Daily bar chart — **operator-local calendar days** (`?tz=`); zero-filled
cells. `chart-*` tokens supply bar tones (accent runs, danger errors).

## Per-agent table

Name | runs | errors | tokens | cost | last active (`toLocaleDateString` local).
Failing agents list uses warning/danger words.

## Version mismatch banner

`WarningBanner tone="danger"` when the dashboard's schema expectation and the
running gateway disagree.

## Export

"Export .xlsx" downloads the same stats incl. the daily series (local days)
and per-agent sheet.

## Honesty rules

- Zero-without-pricing-provenance renders as **unknown**, never $0.00 free.
- Spend scope (platform vs agent) is labeled — the two are intentionally not
  algebraically equal.
