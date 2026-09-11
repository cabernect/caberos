import { X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { dismissToast, useNotificationToasts } from "@/lib/notificationStore";
import type { Notification } from "@/lib/types";

const SEVERITY_COLORS: Record<Notification["severity"], string> = {
  info: "var(--accent)",
  success: "var(--success)",
  warning: "var(--warning, #b45309)",
  error: "var(--danger)",
};

export function NotificationToasts() {
  const navigate = useNavigate();
  const toasts = useNotificationToasts();

  const open = async (item: Notification) => {
    dismissToast(item.id);
    try {
      await api.markNotificationRead(item.id);
    } catch {}
    if (item.action_path) navigate(item.action_path);
    else navigate("/notifications");
  };

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[90] flex w-[320px] flex-col gap-2">
      {toasts.map((item) => (
        <div
          key={item.id}
          role="alert"
          className="pointer-events-auto flex items-start gap-2.5 rounded-[8px] border p-3 shadow-lg"
          style={{
            background: "var(--white)",
            borderColor: "var(--border)",
            borderLeft: `3px solid ${SEVERITY_COLORS[item.severity]}`,
          }}
        >
          <button
            type="button"
            onClick={() => void open(item)}
            className="min-w-0 flex-1 text-left"
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            <p className="text-[13px] font-medium text-[var(--ink)]">{item.title}</p>
            <p className="mt-0.5 line-clamp-2 text-[12px] leading-[1.4] text-[var(--ink-2)]">
              {item.message}
            </p>
          </button>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => dismissToast(item.id)}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--ink-3)] hover:bg-[var(--border)] hover:text-[var(--ink)]"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
