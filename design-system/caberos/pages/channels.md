# Page: Channels

> **Route:** `/channels`
> **Overrides:** `design-system/caberos/MASTER.md`
> **Breadcrumbs:** Capabilities › Channels

"Chat with your agents from the apps you already use."

## Anatomy

PageHeader (+ ⌘K, actions: **Add channel**) → `FilterPills` →
`grid-cols-1 lg:grid-cols-3` — channel list (col-span 2) + detail column.

## Channel list rows

`ListRow`: platform `IconTile` + name + `agent_name` + connected status word
+ `Toggle` (enable). Removal lives in the detail panel (confirm).

## Detail panel

- `KeyValueRow`s: platform, agent, bot identity, status.
- Platform-specific fields (webhook/chat-id config, verification).
- **Test connection** button — explains itself ("sends one request").
- Footer: danger-outline **Remove channel**.

## Add channel modal

`max-w-[440px] max-h-[85vh]` modal (`rounded-2xl`): platform picker grid
(2-col tiles: Telegram / Discord / Zalo OA / Zalo Bot) → per-platform field
form.

## Notes

- Channels route through the same run pipeline + audit as chat; the card
  shows whether the channel process is actually live, not just configured.
