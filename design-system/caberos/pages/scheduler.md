# Page: Scheduler

> **Route:** `/scheduler`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Workspace › Scheduler

Autonomous runs — each occurrence is its own session with its own history.

## Anatomy

PageHeader (title + subtitle + actions: **New schedule**) → `FilterPills`
(Schedules | Heartbeats | Archived) → failure-alert rows → table.

Content rail `mx-auto max-w-5xl`. Rows are grid columns
(`grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_110px_120px_180px]`), not ListRow —
wide data table: name | trigger summary | status | next fire | actions.

## Schedule rows

- **Trigger summary:** "Every 30m", cron expr, "Once — Oct 6, 2:00 PM" —
  `toLocaleString` local rendering; cron carries its own IANA timezone.
- **Status:** `StatusWord` + consecutive-failure badge when > 0.
- **Next fire:** relative + absolute local time (`fmtNext`), "—" when paused.
- **Row actions:** run now / edit (modal) / archive. Archived view adds
  `opacity-75`.
- Click row → detail: occurrence history (per-occurrence status + times)
  + revision history.

## Failure alerts

`WarningBanner`-style rows: "Caber — failed 3 times (threshold: 3)". Schedules
dedupe per **schedule-configured local day**.

## Heartbeats view

Per-agent managed-schedule facade — same grid treatment
(`grid-cols-[minmax(0,2fr)_minmax(0,3fr)_90px_130px_120px]`): agent | prompt
summary | status | cadence | actions. Managed rows reject edit/delete.

## New/Edit schedule modal

Form fields: agent select, name, trigger (once datetime-local / interval /
cron + timezone `Select` from `Intl.supportedValuesOf("timeZone")`), task
prompt, policies (missed/overlap/failure), auto-approve capabilities,
limits. `datetime-local` inputs convert via `getTimezoneOffset` so the stored
instant is correct; preview shows next fires in the schedule's timezone.
