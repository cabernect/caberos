/**
 * OS-level notification adapters (W9).
 *
 * Exactly one owns the OS surface: in the Tauri shell that's the native
 * plugin (`system`), everywhere else the browser Notification API
 * (`browser`). Never both. Permission is opt-in — callers check state and
 * degrade to inbox + toast on `denied`/`unavailable`.
 */

import { isDesktopMode } from "./updater";
import type { Notification } from "./types";

export type OsAdapter = "browser" | "system";

export function osAdapter(): OsAdapter {
  return isDesktopMode() ? "system" : "browser";
}

export type OsPermission = "granted" | "denied" | "default" | "unavailable";

/** Desktop OS-level truth — the plugin's own permission check is
 *  hardcoded Granted on desktop (its legacy backend predates macOS's
 *  permission model). Our Tauri command queries UNUserNotificationCenter,
 *  which sees the System Settings toggle (B41). */
async function desktopOsState(): Promise<OsPermission> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const s = await invoke<string>("notification_os_state");
    return s === "granted" || s === "denied" || s === "default" ? s : "unavailable";
  } catch {
    return "unavailable";
  }
}

export async function osPermissionState(): Promise<OsPermission> {
  if (osAdapter() === "system") return desktopOsState();
  if (typeof window === "undefined" || !("Notification" in window)) return "unavailable";
  return window.Notification.permission as OsPermission;
}

/** Must be called inside a user gesture (browser requirement). */
export async function requestOsPermission(): Promise<OsPermission> {
  if (osAdapter() === "system") {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      if ((await desktopOsState()) === "granted") return "granted";
      const s = await invoke<string>("notification_os_request");
      return s === "granted" ? "granted" : s === "denied" ? "denied" : s === "default" ? "default" : "unavailable";
    } catch {
      return "unavailable";
    }
  }
  if (typeof window === "undefined" || !("Notification" in window)) return "unavailable";
  try {
    const p = await window.Notification.requestPermission();
    return p as OsPermission;
  } catch {
    return "unavailable";
  }
}

export type DeliveryOutcome = { state: "delivered" | "failed"; error?: string };

/** Fire the OS notification. `onClick` runs when the operator clicks it —
 *  browser path wires onclick; Tauri's plugin has no click callback, so
 *  deep-link there relies on the operator opening the app. */
export async function deliverOs(
  n: Notification,
  onClick: () => void,
): Promise<DeliveryOutcome> {
  let perm = await osPermissionState();
  if (perm === "default") {
    // Never asked at OS level — UN drops posts from never-authorized
    // apps silently, so ask once here rather than lose the ping.
    perm = await requestOsPermission();
  }
  // "unavailable" = platform has no queryable permission model (Windows,
  // Linux, unbundled dev). The send call itself is the honest check there —
  // only "denied"/unresolved "default" are proof the OS would drop it.
  if (perm !== "granted" && perm !== "unavailable") {
    return { state: "failed", error: `permission_${perm}` };
  }
  try {
    if (osAdapter() === "system") {
      const { invoke } = await import("@tauri-apps/api/core");
      try {
        // Own command, not the plugin's sendNotification — that one spawns a
        // detached task and discards the result, and its macOS path bails
        // (silently) whenever the main run loop is busy — which is exactly
        // when run-completion pings fire (B43).
        await invoke("notification_os_send", { title: n.title, body: n.message });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg !== "unavailable") return { state: "failed", error: msg };
        // Non-macOS desktop: no UN command — the plugin is the only sender
        // and reports nothing, so "delivered" means dispatched.
        const { sendNotification } = await import("@tauri-apps/plugin-notification");
        sendNotification({ title: n.title, body: n.message });
      }
      return { state: "delivered" };
    }
    const notif = new window.Notification(n.title, {
      body: n.message,
      tag: n.event_id ?? n.id,
    });
    notif.onclick = () => {
      window.focus();
      onClick();
    };
    return { state: "delivered" };
  } catch (e) {
    return { state: "failed", error: e instanceof Error ? e.message : String(e) };
  }
}
