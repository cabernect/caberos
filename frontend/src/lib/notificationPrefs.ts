/**
 * Notification preferences (W9) — cached blob + matrix resolution +
 * quiet-hours evaluation. The blob lives server-side (operator settings)
 * so browser and Tauri shells share it.
 */

import { api } from "./api";
import { broadcastPrefsChanged } from "./crossTab";
import type {
  NotificationPrefs,
  NotificationPrefsPatch,
  NotifSurface,
  SurfacePrefs,
} from "./types";

const DEFAULT_PREFS: NotificationPrefs = {
  defaults: { inbox: true, toast: true, browser: false, system: false },
  overrides: {},
  quiet_hours: { enabled: false, start: "22:00", end: "07:00", tz: null },
  permissions: { browser_asked: false, tauri_asked: false },
};

let prefs: NotificationPrefs = DEFAULT_PREFS;
const listeners = new Set<() => void>();

export async function loadNotificationPrefs(): Promise<NotificationPrefs> {
  try {
    prefs = await api.getNotificationPrefs();
  } catch {
    // Offline/early boot — keep defaults.
  }
  return prefs;
}

export function getNotificationPrefs(): NotificationPrefs {
  return prefs;
}

/** Mirror of the backend's merge rules — dict-valued keys merge shallowly
 *  onto the existing blob; `overrides` merges per event type with `null`
 *  deleting the entry (explicit delete survives where omission couldn't). */
function applyPatch(
  base: NotificationPrefs,
  patch: NotificationPrefsPatch,
): NotificationPrefs {
  const merged: NotificationPrefs = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    const k = key as keyof NotificationPrefs;
    if (k === "overrides" && value && typeof value === "object") {
      const cur = { ...(merged.overrides ?? {}) };
      for (const [type, override] of Object.entries(value)) {
        if (override == null) delete cur[type];
        else cur[type] = override as Partial<SurfacePrefs>;
      }
      merged.overrides = cur;
      continue;
    }
    const cur = merged[k];
    if (
      value !== null &&
      typeof value === "object" &&
      cur !== null &&
      typeof cur === "object"
    ) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (merged as any)[k] = { ...(cur as object), ...(value as object) };
    } else {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (merged as any)[k] = value;
    }
  }
  return merged;
}

export async function saveNotificationPrefs(
  patch: NotificationPrefsPatch,
): Promise<NotificationPrefs> {
  // Optimistic: local state applies now (the coordinator reads this
  // cache), the PUT persists it. If the write fails the change still
  // holds for this session rather than snapping the UI back.
  prefs = applyPatch(prefs, patch);
  for (const cb of listeners) cb();
  try {
    // Send the patch, not the merged blob — a whole-blob PUT lets a stale
    // tab revert fields it never touched (B35).
    prefs = await api.putNotificationPrefs(patch);
    for (const cb of listeners) cb();
    // Peer tabs re-fetch — the leader's suppression matrix can't drift (B36).
    broadcastPrefsChanged();
  } catch {
    // Persist failed — local copy stands until reload.
  }
  return prefs;
}

export function onPrefsChange(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Per-event x per-surface resolution: override wins, else default. */
export function surfaceEnabled(type: string, surface: NotifSurface): boolean {
  return prefs.overrides[type]?.[surface] ?? prefs.defaults[surface];
}

/** Quiet hours — uniform suppression of all attention surfaces.
 *  Overnight windows (22:00→07:00) wrap midnight. Evaluated in local time;
 *  `tz` is reserved for a future per-zone override. */
export function inQuietHours(now: Date = new Date()): boolean {
  const q = prefs.quiet_hours;
  if (!q.enabled) return false;
  const [sh, sm] = q.start.split(":").map(Number);
  const [eh, em] = q.end.split(":").map(Number);
  if ([sh, sm, eh, em].some((v) => Number.isNaN(v))) return false;
  const cur = now.getHours() * 60 + now.getMinutes();
  const start = sh * 60 + sm;
  const end = eh * 60 + em;
  return start <= end ? cur >= start && cur < end : cur >= start || cur < end;
}
