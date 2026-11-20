/**
 * macOS Dock badge — mirrors the unread inbox count onto the app icon.
 * Desktop shell only; no-op on web and non-macOS builds (the Tauri command
 * itself is a no-op there). Failures reset the cache so the next change
 * retries instead of sticking on a stale count.
 */

import { isDesktopMode } from "./updater";

let lastCount = -1;

export function syncDockBadge(unread: number) {
  if (!isDesktopMode() || unread === lastCount) return;
  lastCount = unread;
  void import("@tauri-apps/api/core")
    .then(({ invoke }) => invoke("set_dock_badge", { count: unread }))
    .catch(() => {
      lastCount = -1;
    });
}
