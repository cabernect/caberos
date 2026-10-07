import { useEffect, useState } from "react";
import { BellRing, X } from "lucide-react";
import {
  loadNotificationPrefs,
  saveNotificationPrefs,
} from "@/lib/notificationPrefs";
import { useNotifications } from "@/lib/notificationStore";
import {
  osAdapter,
  osPermissionState,
  requestOsPermission,
} from "@/lib/notifAdapters";

/**
 * The single opt-in banner (W9). Appears once — after the first real
 * notification lands in the inbox — while the OS-level grant is still
 * undecided and we haven't asked. Enable, deny, and dismiss all persist
 * `asked: true`; we never re-prompt.
 */
export function NotificationPermissionBanner() {
  const [visible, setVisible] = useState(false);
  const [decided, setDecided] = useState(false);
  const items = useNotifications();
  const os = osAdapter();
  const askedKey = os === "system" ? "tauri_asked" : "browser_asked";

  useEffect(() => {
    if (decided) return;
    // Wait for a real event before offering — never prompt cold.
    if (items.length === 0) return;
    let alive = true;
    void (async () => {
      const prefs = await loadNotificationPrefs();
      const perm = await osPermissionState();
      if (!alive) return;
      if (perm === "default" && !prefs.permissions[askedKey]) {
        setVisible(true);
      } else {
        setDecided(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [items.length, decided, askedKey]);

  if (!visible) return null;

  const markAsked = async (granted: boolean) => {
    try {
      await saveNotificationPrefs({
        permissions: { [askedKey]: true },
        // Grant turns the surface on — otherwise "Enable" would be a no-op.
        // Patch only owned keys — a stale tab must not re-assert the blob (B35).
        ...(granted ? { defaults: { [os]: true } } : {}),
      });
    } catch {
      // Best-effort persist — the banner still closes; worst case it asks
      // once more next session.
    }
  };

  const close = () => {
    setDecided(true);
    setVisible(false);
  };

  const enable = async () => {
    const result = await requestOsPermission().catch(() => "unavailable" as const); // click = user gesture
    await markAsked(result === "granted");
    close();
  };

  const dismiss = async () => {
    await markAsked(false);
    close();
  };

  return (
    <div
      className="pointer-events-auto fixed bottom-5 left-1/2 z-[95] flex w-[min(430px,90vw)] -translate-x-1/2 items-start gap-3 rounded-[8px] border p-3 shadow-lg"
      style={{ background: "var(--white)", borderColor: "var(--accent)" }}
      role="dialog"
      aria-label="Enable notifications"
    >
      <BellRing className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-[var(--ink)]">
          Enable {os === "system" ? "desktop" : "browser"} notifications?
        </p>
        <p className="mt-0.5 text-[12px] text-[var(--ink-2)]">
          Get alerts when you’re not looking at CaberOS. The inbox keeps
          everything either way — this only controls pings.
        </p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => void enable()}
            className="rounded-[5px] px-3 py-1 text-[12px] font-medium text-white"
            style={{ background: "var(--accent)", border: "none", cursor: "pointer" }}
          >
            Enable
          </button>
          <button
            type="button"
            onClick={() => void dismiss()}
            className="rounded-[5px] px-3 py-1 text-[12px] text-[var(--ink-2)]"
            style={{ background: "none", border: "none", cursor: "pointer" }}
          >
            Not now
          </button>
        </div>
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => void dismiss()}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--ink-3)] hover:bg-[var(--border)]"
        style={{ border: "none", background: "none", cursor: "pointer" }}
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
