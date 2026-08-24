import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { checkForUpdates, downloadAndInstallUpdate, isDesktopMode, type UpdateInfo } from "@/lib/updater";

/**
 * Auto-check for updates on startup in desktop mode.
 * Shows a popup alert if a new version is available.
 * Does nothing in web mode.
 */
export function UpdateChecker() {
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState<{ downloaded?: number; total?: number }>({});

  useEffect(() => {
    if (!isDesktopMode()) return;
    // Check after a short delay so startup isn't blocked
    const timer = setTimeout(async () => {
      const info = await checkForUpdates();
      if (info.available) {
        setUpdateInfo(info);
      }
    }, 3000);
    return () => clearTimeout(timer);
  }, []);

  if (!updateInfo || dismissed) return null;

  const handleUpdate = async () => {
    setDownloading(true);
    try {
      await downloadAndInstallUpdate((p) => setProgress(p));
      // App restarts automatically after install
    } catch (e) {
      console.error("Update failed:", e);
      setDownloading(false);
    }
  };

  const pct = progress.total && progress.downloaded
    ? Math.round((progress.downloaded / progress.total) * 100)
    : null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex items-start gap-3 rounded-lg border p-4 shadow-lg"
      style={{
        borderColor: "var(--accent)",
        background: "var(--white)",
        maxWidth: "380px",
      }}
    >
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
        style={{ background: "var(--accent)" }}
      >
        <Download className="h-4 w-4 text-white" />
      </div>
      <div className="flex-1">
        <p className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          New update available
        </p>
        <p className="mt-0.5 text-[12px]" style={{ color: "var(--ink-2)" }}>
          v{updateInfo.latestVersion} is ready to install
          {updateInfo.currentVersion !== "unknown" && ` (you have v${updateInfo.currentVersion})`}
        </p>
        {updateInfo.notes && (
          <p className="mt-1 text-[11px] line-clamp-2" style={{ color: "var(--ink-3)" }}>
            {updateInfo.notes}
          </p>
        )}
        {downloading ? (
          <div className="mt-2">
            <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--surface)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: pct !== null ? `${pct}%` : "100%",
                  background: "var(--accent)",
                }}
              />
            </div>
            <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
              {pct !== null ? `${pct}% — downloading…` : "Installing…"}
            </p>
          </div>
        ) : (
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
      {!downloading && (
        <button
          onClick={() => setDismissed(true)}
          className="rounded p-0.5"
          style={{ color: "var(--ink-3)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
