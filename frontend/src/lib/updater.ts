import { useSyncExternalStore } from "react";

/**
 * Auto-update utilities for CaberOS desktop.
 *
 * Uses the Tauri v2 updater plugin to check for, download, and install
 * signed updates from GitHub releases. The updater signing key is not stored
 * in GitHub; it is used by the release workflow to sign update archives.
 */

export interface UpdateInfo {
  available: boolean;
  currentVersion: string;
  latestVersion?: string;
  notes?: string;
  downloadUrl?: string;
}

export type UpdateStatus = "idle" | "checking" | "available" | "downloading" | "installing" | "ready" | "up-to-date" | "error";

export interface UpdaterState {
  info: UpdateInfo | null;
  status: UpdateStatus;
  progress: { downloaded?: number; total?: number };
  error: string;
}

const initialState: UpdaterState = { info: null, status: "idle", progress: {}, error: "" };
let state = initialState;
const listeners = new Set<() => void>();

function setState(next: Partial<UpdaterState>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

export function useUpdater(): UpdaterState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/**
 * Check if we're running inside the Tauri desktop shell.
 */
export function isDesktopMode(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Check for available updates using the Tauri updater plugin.
 */
export async function checkForUpdates(): Promise<UpdateInfo> {
  if (!isDesktopMode()) return { available: false, currentVersion: "web" };

  const updater = await import("@tauri-apps/plugin-updater");
  const update = await updater.check();
  if (update) {
    return {
      available: true,
      currentVersion: update.currentVersion,
      latestVersion: update.version,
      notes: update.body,
    };
  }

  const app = await import("@tauri-apps/api/app");
  return { available: false, currentVersion: await app.getVersion() };
}

export async function refreshUpdates(): Promise<UpdateInfo> {
  setState({ status: "checking", error: "" });
  try {
    const info = await checkForUpdates();
    setState({ info, status: info.available ? "available" : "up-to-date" });
    return info;
  } catch (error) {
    const message = String(error);
    setState({ status: "error", error: message });
    throw error;
  }
}

/**
 * Download and install the update without restarting the app.
 * The UI shows the ready state and lets the user choose when to relaunch.
 */
export async function downloadAndInstallUpdate(): Promise<void> {
  if (!isDesktopMode()) throw new Error("Auto-update is only available in desktop mode");

  const updater = await import("@tauri-apps/plugin-updater");
  const update = await updater.check();
  if (!update) throw new Error("No update available");

  let downloaded = 0;
  let total = 0;
  setState({ status: "downloading", progress: {}, error: "" });

  await update.downloadAndInstall((event) => {
    switch (event.event) {
      case "Started":
        total = event.data.contentLength ?? 0;
        setState({ progress: { total, downloaded: 0 } });
        break;
      case "Progress":
        downloaded += event.data.chunkLength;
        setState({ progress: { total, downloaded } });
        break;
      case "Finished":
        setState({ status: "installing", progress: { total, downloaded: total } });
        break;
    }
  });

  await update.close();
  setState({ status: "ready", progress: { total, downloaded: total } });
}

export async function restartApp(): Promise<void> {
  if (!isDesktopMode()) throw new Error("Restart is only available in desktop mode");
  const process = await import("@tauri-apps/plugin-process");
  await process.relaunch();
}

export function resetUpdater(): void {
  setState(initialState);
}
