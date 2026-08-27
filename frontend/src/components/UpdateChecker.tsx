import { useEffect, useState } from "react";
import { Download, RotateCcw, X } from "lucide-react";
import {
  downloadAndInstallUpdate,
  isDesktopMode,
  refreshUpdates,
  restartApp,
  useUpdater,
} from "@/lib/updater";

/**
 * Auto-check for updates on startup in desktop mode.
 * Shows a popup alert if a new version is available.
 * Does nothing in web mode.
 */
export function UpdateChecker() {
  const updater = useUpdater();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!isDesktopMode()) return;
    // Check after a short delay so startup isn't blocked
    const timer = setTimeout(() => {
      void refreshUpdates().catch(() => {});
    }, 3000);
    return () => clearTimeout(timer);
  }, []);

  if (!updater.info?.available || dismissed) return null;

  const handleUpdate = async () => {
    try {
      await downloadAndInstallUpdate();
    } catch (error) {
      console.error("Update failed:", error);
    }
  };

  const handleRestart = async () => {
    try {
      await restartApp();
    } catch (error) {
      console.error("Restart failed:", error);
    }
  };

  const { downloaded, total } = updater.progress;
  const pct = total ? Math.min(100, Math.round(((downloaded || 0) / total) * 100)) : null;
  const isBusy = updater.status === "downloading" || updater.status === "installing";

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex items-start gap-3 rounded-lg border p-4 shadow-lg"
      style={{ borderColor: "var(--accent)", background: "var(--white)", maxWidth: "380px" }}
    >
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
        style={{ background: "var(--accent)" }}
      >
        {updater.status === "ready" ? <RotateCcw className="h-4 w-4 text-white" /> : <Download className="h-4 w-4 text-white" />}
      </div>
      <div className="flex-1">
        <p className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          {updater.status === "ready" ? "Update installed" : "New update available"}
        </p>
        <p className="mt-0.5 text-[12px]" style={{ color: "var(--ink-2)" }}>
          {updater.status === "ready"
            ? `Restart to use v${updater.info.latestVersion}`
            : `v${updater.info.latestVersion} is ready to install${updater.info.currentVersion !== "unknown" ? ` (you have v${updater.info.currentVersion})` : ""}`}
        </p>
        {updater.info.notes && updater.status === "available" && (
          <p className="mt-1 line-clamp-2 text-[11px]" style={{ color: "var(--ink-3)" }}>
            {updater.info.notes}
          </p>
        )}
        {isBusy && (
          <div className="mt-2">
            <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--surface)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{ width: updater.status === "installing" ? "100%" : `${pct ?? 0}%`, background: "var(--accent)" }}
              />
            </div>
            <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
              {updater.status === "installing" ? "Installing…" : `${pct ?? 0}% — downloading…`}
            </p>
          </div>
        )}
        {updater.status === "ready" && (
          <button
            onClick={handleRestart}
            className="mt-2 flex items-center gap-1.5 rounded-md px-3 py-1 text-[12px] font-medium text-white"
            style={{ background: "var(--accent)" }}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Restart now
          </button>
        )}
        {updater.status === "error" && (
          <p className="mt-2 text-[11px] text-[var(--danger)]">
            {updater.error || "Update failed. Please try again."}
          </p>
        )}
        {updater.status === "available" && (
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => setDismissed(true)}
              className="rounded-md border px-3 py-1 text-[12px]"
              style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
            >
              Later
            </button>
            <button
              onClick={handleUpdate}
              className="rounded-md px-3 py-1 text-[12px] font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              Update now
            </button>
          </div>
        )}
      </div>
      {!isBusy && updater.status !== "ready" && (
        <button onClick={() => setDismissed(true)} className="rounded p-0.5" style={{ color: "var(--ink-3)" }}>
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
