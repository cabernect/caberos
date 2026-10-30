# Page: Settings

> **Route:** `/settings`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Workspace › Settings

"Manage your CaberOS configuration." (`ProvidersSettings.tsx` — the file name
is historic; the page is global Settings.)

## Anatomy

PageHeader → `FilterPills` section nav → `max-w-4xl space-y-*` stacked
sections (`<section id>` + 14px semibold h2 + body).

## Sections

- **Operator** — account card (username, password change).
- **Providers** — provider list + add/edit; `ModelPicker` browse + **Test
  connection** (probes cheapest tool-capable model, explains it records a
  probe call in the ledger).
- **General** — Optional Tools & Runtimes (`OptionalToolsAndRuntimes`):
  app-managed installs, fixed recipes, consent-gated — no silent downloads.
- **Agent browser** — managed Chrome-for-Testing install state (explicit
  first-use consent), headless/visible, domain leash, profiles.
- **Saved logins** — domain-scoped credential rows (mono host, trash).
- **Appearance** — theme `Select`: light / dark / system (`caberos-theme`).

## Per-agent settings

Not this page — `SettingsOverlay` opens from Agents/Conversation (model,
permissions, limits, heartbeat, channels).
