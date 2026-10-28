# Page: Knowledge Vault

> **Route:** `/vault`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Capabilities › Knowledge Vault

"What your agents can read and remember." Subtitle carries live scope count.

## Anatomy

PageHeader → **ask bar** ("Vault answers for …") → 2-col grid
(`lg:grid-cols-2`): scope cards left, documents/search right — wraps to one
column on narrow.

## Ask bar

Same treatment as Today's composer: `border-line bg-surface` form, textarea +
ask → `SectionCard` "Vault answers for *query*" showing retrieval results
with citations + retrieval trace honest about what matched.

## Scope cards

`SectionCard` per scope (agent / global): doc count + chunk count
(`toLocaleString`), index status, actions (rebuild — blue-green generation,
409 on concurrent), degraded-index `WarningBanner` when applicable.

## Documents

Per-scope rows: file tile + display name + chunk count + size + indexed date
(local). Tabular uploads (.xlsx/.csv) refuse at ingest — the card explains
why, not an error toast.

## Embeddings / hybrid state

Lexical FTS5 is the default; hybrid embedding is opt-in — egress consent is
shown as an explicit toggle/explainer, never silently on.
