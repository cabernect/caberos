import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";

export function NotificationCenter({ sidebar = false, active = false }: { sidebar?: boolean; active?: boolean }) {
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);

  const load = useCallback(() => {
    api.listNotifications().then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [load]);

  const unread = items.filter((item) => !item.read).length;

  return (
    <div className={sidebar ? "relative z-[80] w-full" : "fixed right-5 top-5 z-[80]"}>
      <button
        type="button"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        onClick={() => navigate("/notifications")}
        className={sidebar
          ? "relative flex h-8 w-full items-center justify-start gap-2 rounded-[5px] px-2.5 py-2 text-[13px] transition-colors"
          : "relative flex h-9 w-9 items-center justify-center rounded-full border shadow-sm transition-colors hover:bg-[var(--hover)]"}
        style={{ background: active ? "var(--ink)" : "none", borderColor: "var(--border)", color: active ? "var(--white)" : "var(--ink-2)", cursor: "pointer", fontWeight: active ? 500 : 400 }}
        onMouseEnter={(event) => {
          event.currentTarget.style.background = active ? "var(--ink-2)" : "var(--border)";
          event.currentTarget.style.color = active ? "var(--white)" : "var(--ink)";
        }}
        onMouseLeave={(event) => {
          event.currentTarget.style.background = active ? "var(--ink)" : "none";
          event.currentTarget.style.color = active ? "var(--white)" : "var(--ink-2)";
        }}
      >
        <Bell className="h-4 w-4" />
        {sidebar && <span>Notifications</span>}
        {unread > 0 && <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white" style={{ background: "var(--danger)" }}>{unread > 9 ? "9+" : unread}</span>}
      </button>
    </div>
  );
}
