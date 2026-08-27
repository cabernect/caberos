import { useCallback, useEffect, useState } from "react";
import { Bell, Check, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";

export function NotificationCenter() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    api.listNotifications().then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [load]);

  const unread = items.filter((item) => !item.read).length;
  const markAllRead = async () => {
    await api.markAllNotificationsRead();
    setItems((current) => current.map((item) => ({ ...item, read: true })));
  };

  return (
    <div className="fixed right-5 top-5 z-[80]">
      <button
        type="button"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        onClick={() => setOpen((value) => !value)}
        className="relative flex h-9 w-9 items-center justify-center rounded-full border shadow-sm transition hover:bg-[var(--hover)]"
        style={{ background: "var(--white)", borderColor: "var(--border)", color: "var(--ink-2)", cursor: "pointer" }}
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white" style={{ background: "var(--danger)" }}>{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <section className="absolute right-0 mt-2 w-80 rounded-lg border p-3 shadow-xl" style={{ background: "var(--white)", borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between border-b pb-2" style={{ borderColor: "var(--border)" }}>
            <h2 className="text-[13px] font-semibold text-[var(--ink)]">Notifications</h2>
            <div className="flex items-center gap-1">
              {unread > 0 && <button type="button" onClick={() => void markAllRead()} className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--hover)]" title="Mark all as read"><Check className="h-3.5 w-3.5" /></button>}
              <button type="button" onClick={() => setOpen(false)} className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--hover)]" title="Close notifications"><X className="h-3.5 w-3.5" /></button>
            </div>
          </div>
          {items.length === 0 ? <p className="py-6 text-center text-[12px] text-[var(--ink-3)]">You’re all caught up.</p> : <div className="max-h-96 overflow-y-auto">{items.map((item) => <button key={item.id} type="button" onClick={() => { void api.markNotificationRead(item.id); setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, read: true } : entry)); if (item.action_path) navigate(item.action_path); }} className="w-full border-b px-1 py-3 text-left last:border-0 hover:bg-[var(--hover)]" style={{ borderColor: "var(--border)", opacity: item.read ? 0.65 : 1, cursor: "pointer" }}><div className="flex items-start justify-between gap-2"><p className="text-[12px] font-semibold text-[var(--ink)]">{item.title}</p><span className="text-[10px] uppercase text-[var(--ink-3)]">{item.severity}</span></div><p className="mt-1 text-[12px] leading-5 text-[var(--ink-2)]">{item.message}</p></button>)}</div>}
        </section>
      )}
    </div>
  );
}
