import { useEffect, useState } from "react";
import {
  getNotificationPrefs,
  loadNotificationPrefs,
  onPrefsChange,
  saveNotificationPrefs,
} from "@/lib/notificationPrefs";
import {
  osAdapter,
  osPermissionState,
  requestOsPermission,
  type OsPermission,
} from "@/lib/notifAdapters";
import type { NotifSurface, SurfacePrefs } from "@/lib/types";
import { IS_MAC } from "@/lib/platform";
import { Toggle } from "@/components/ui/toggle";
import { Select } from "@/components/ui/select";

/** Known event types — surfaced in the override editor. Anything not
 *  listed still resolves through the defaults row. */
const EVENT_TYPES: { type: string; label: string }[] = [
  { type: "run_completed", label: "Run completed" },
  { type: "run_failed", label: "Run failed" },
  { type: "run_interrupted", label: "Run interrupted" },
  { type: "approval_required", label: "Approval required" },
  { type: "elicitation_required", label: "Question from agent" },
  { type: "schedule_failed", label: "Schedule failures" },
  { type: "mcp_connection_failed", label: "MCP connection failed" },
  { type: "oauth_reauth_required", label: "OAuth re-auth required" },
  { type: "skill_publish_failed", label: "Skill publish failed" },
  { type: "vault_index_degraded", label: "Vault index degraded" },
  { type: "browser_takeover_required", label: "Browser takeover required" },
  { type: "update_available", label: "App update available" },
];

type OverrideChoice = "default" | "muted" | "desktop";

function overrideChoice(
  overrides: Record<string, Partial<SurfacePrefs>>,
  type: string,
  os: NotifSurface,
): OverrideChoice {
  const o = overrides[type];
  if (!o) return "default";
  if (o.toast === false && o[os] === false) return "muted";
  if (o.toast === true && o[os] === true) return "desktop";
  return "default";
}

/** The single notifications control. One toggle governs every attention
 *  surface — in-app toasts plus the OS ping (browser Notification on web,
 *  the Tauri plugin in the desktop app). Switching on while permission is
 *  undecided fires the browser/OS prompt inside the same click gesture;
 *  a grant enables the OS surface in the same motion. The inbox is not a
 *  surface — it always records, so there is nothing to switch. */
export function NotificationPrefsForm() {
  const [prefs, setPrefs] = useState(getNotificationPrefs());
  const [perm, setPerm] = useState<OsPermission>("default");
  const [asking, setAsking] = useState(false);
  const os = osAdapter();

  useEffect(() => {
    void loadNotificationPrefs().then(setPrefs);
    const recheck = () => void osPermissionState().then(setPerm);
    recheck();
    // macOS-level toggles change outside the app — refresh on focus so the
    // "blocked in OS settings" hint reflects the real state (B41).
    window.addEventListener("focus", recheck);
    const unsub = onPrefsChange(() => setPrefs(getNotificationPrefs()));
    return () => {
      window.removeEventListener("focus", recheck);
      unsub();
    };
  }, []);

  const patch = (p: Parameters<typeof saveNotificationPrefs>[0]) => {
    void saveNotificationPrefs(p).then(setPrefs).catch(() => {});
  };

  const enabled = prefs.defaults.toast || prefs.defaults[os];

  const toggleAll = (on: boolean) => {
    if (!on) {
      patch({ defaults: { toast: false, [os]: false } });
      return;
    }
    // Flip immediately — the toggle never waits on the permission prompt:
    // some browsers leave requestPermission() pending forever when the
    // prompt is dismissed, which froze the toggle mid-flight before.
    // Patch only the keys this action owns — a stale tab must not
    // re-assert the rest of the blob (B35).
    patch({
      defaults: { toast: true, [os]: perm === "granted" },
      permissions: {
        [os === "system" ? "tauri_asked" : "browser_asked"]: true,
      },
    });
    if (perm === "granted" || perm !== "default" || asking) return;
    setAsking(true); // re-entry guard only — never gates the toggle
    void requestOsPermission()
      .then((result) => {
        setPerm(result);
        // A late "Allow" only turns the OS surface on if the toggle is
        // still on — the user may have switched off while deciding.
        const cur = getNotificationPrefs();
        if (result === "granted" && cur.defaults.toast) {
          patch({ defaults: { [os]: true } });
        }
      })
      .finally(() => setAsking(false));
  };

  const setOverride = (type: string, choice: OverrideChoice) => {
    const override =
      choice === "default"
        ? null // explicit delete — the only way to clear a key
        : choice === "muted"
          ? { toast: false, browser: false, system: false }
          : { toast: true, browser: true, system: true };
    patch({ overrides: { [type]: override } });
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium text-[var(--ink)]">
            Enable notifications
          </p>
          <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
            In-app toasts and {os === "system" ? "desktop" : "browser"} alerts.
            The inbox always records everything.
          </p>
          {perm === "denied" && enabled && (
            <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
              {os === "system" ? "Desktop" : "Browser"} alerts are blocked —
              enable them in{" "}
              {os === "system" ? (
                IS_MAC ? (
                  <button
                    type="button"
                    className="underline underline-offset-2"
                    onClick={() => {
                      void import("@tauri-apps/plugin-opener").then((m) =>
                        m.openUrl(
                          "x-apple.systempreferences:com.apple.Notifications-Settings",
                        ),
                      );
                    }}
                  >
                    macOS notification settings
                  </button>
                ) : (
                  "system notification settings"
                )
              ) : (
                "browser site settings"
              )}
              .
            </p>
          )}
        </div>
        <Toggle
          checked={enabled}
          onCheckedChange={toggleAll}
          aria-label="Enable notifications"
        />
      </div>

      {/* Quiet hours */}
      <div
        className="mt-4 border-t pt-4"
        style={{ borderColor: "var(--border-soft)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] font-medium text-[var(--ink)]">
            Quiet hours
          </p>
          <div className="flex items-center gap-3">
            <input
              type="time"
              value={prefs.quiet_hours.start}
              disabled={!prefs.quiet_hours.enabled}
              onChange={(e) =>
                patch({ quiet_hours: { start: e.target.value } })
              }
              className="w-[76px] rounded-md border px-2 py-1.5 text-center text-[13px] disabled:opacity-50"
              style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
            />
            <span className="text-[13px] text-[var(--ink-3)]">to</span>
            <input
              type="time"
              value={prefs.quiet_hours.end}
              disabled={!prefs.quiet_hours.enabled}
              onChange={(e) =>
                patch({ quiet_hours: { end: e.target.value } })
              }
              className="w-[76px] rounded-md border px-2 py-1.5 text-center text-[13px] disabled:opacity-50"
              style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
            />
            <Toggle
              checked={prefs.quiet_hours.enabled}
              onCheckedChange={(on) =>
                patch({ quiet_hours: { enabled: on } })
              }
              aria-label="Quiet hours"
            />
          </div>
        </div>
        <p className="mt-1.5 text-[12px] text-[var(--ink-3)]">
          Pauses alerts during these hours. Approvals and questions still
          reach you because they block a run; the inbox records everything.
        </p>
      </div>

      {/* Per-event overrides */}
      <details
        className="mt-4 border-t pt-3.5"
        style={{ borderColor: "var(--border-soft)" }}
      >
        <summary
          className="cursor-pointer text-[13px] font-medium text-[var(--ink)]"
          style={{ listStylePosition: "inside" }}
        >
          Per-event overrides
        </summary>
        <div className="mt-2 divide-y" style={{ borderColor: "var(--border-soft)" }}>
          {EVENT_TYPES.map(({ type, label }) => (
            <div
              key={type}
              className="flex items-center justify-between gap-3 py-2.5"
              style={{ borderColor: "var(--border-soft)" }}
            >
              <span className="truncate text-[13px] text-[var(--ink)]">{label}</span>
              <Select
                value={overrideChoice(prefs.overrides, type, os)}
                onChange={(v) => setOverride(type, v as OverrideChoice)}
                options={[
                  { value: "default", label: "Default" },
                  { value: "muted", label: "Inbox only" },
                  { value: "desktop", label: "Toast + desktop ping" },
                ]}
                className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink"
              />
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
