/**
 * Auto-update utilities for CaberOS desktop (v0.1.3).
 *
 * Uses the Tauri v2 updater plugin to check for, download, and install
 * signed updates from GitHub releases. In web mode, these functions
 * are no-ops that report "not available".
 */

export interface UpdateInfo {
  available: boolean;
  currentVersion: string;
  latestVersion?: string;
  notes?: string;
  downloadUrl?: string;
}

/**
 * Check if we're running inside the Tauri desktop shell.
 */
export function isDesktopMode(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Check for available updates.
 *
 * In desktop mode, uses the Tauri updater plugin.
 * In web mode, returns { available: false }.
 */
export async function checkForUpdates(): Promise<UpdateInfo> {
  if (!isDesktopMode()) {
    return { available: false, currentVersion: "web" };
  }

  try {
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

    // No update available — get current version for display
    const app = await import("@tauri-apps/api/app");
    const currentVersion = await app.getVersion();
    return { available: false, currentVersion };
  } catch (e) {
    // Degrade quietly — the app remains usable
    console.error("Update check failed:", e);
    return { available: false, currentVersion: "unknown", notes: String(e) };
  }
}

/**
 * Download and install the update, then restart the app.
 *
 * The Tauri updater handles signature verification internally.
 * If the signature is invalid, the update is rejected.
 */
export async function downloadAndInstallUpdate(
  onProgress?: (progress: { total?: number; downloaded?: number }) => void,
): Promise<void> {
  if (!isDesktopMode()) {
    throw new Error("Auto-update is only available in desktop mode");
  }

  const updater = await import("@tauri-apps/plugin-updater");
  const update = await updater.check();

  if (!update) {
    throw new Error("No update available");
  }

  let downloaded = 0;
  let total = 0;

  await update.downloadAndInstall((event) => {
    switch (event.event) {
      case "Started":
        total = event.data.contentLength ?? 0;
        break;
      case "Progress":
        downloaded += event.data.chunkLength;
        onProgress?.({ total, downloaded });
        break;
      case "Finished":
        onProgress?.({ total, downloaded: total });
        break;
    }
  });

  // The updater will restart the app automatically after installation.
  // The bundled gateway is terminated by Tauri's shutdown handler.
  await update.close();
}
