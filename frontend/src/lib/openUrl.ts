/**
 * Open a URL in the system's default browser.
 *
 * In the Tauri desktop app, window.open() does not work — we need to use
 * the Tauri opener plugin to launch the system browser.
 * In the web app, window.open() works fine.
 */
export async function openUrl(url: string): Promise<void> {
  // Check if we're running inside Tauri
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    try {
      const { openUrl: tauriOpenUrl } = await import("@tauri-apps/plugin-opener");
      await tauriOpenUrl(url);
    } catch {
      // Fallback to window.open if the plugin isn't available
      window.open(url, "_blank");
    }
  } else {
    window.open(url, "_blank");
  }
}
