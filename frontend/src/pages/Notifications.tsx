import { useCallback, useEffect, useState } from "react";
import { Bell, Check, CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";

const severityIcon = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  error: CircleAlert,
} as const;

const severityColor = {
  info: "var(--ink-3)",
  success: "var(--success)",
  warning: "var(--warning)",
  error: "var(--danger)",
} as const;

type Filter = "all" | "unread";

export function Notifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      setItems(await api.listNotifications());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), 15000);
    return () => clearInterval(interval);
  }, [load]);

  const markRead = async (item: Notification) => {
    if (item.read) return;
    await api.markNotificationRead(item.id);
    setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, read: true } : entry));
  };

  const markAllRead = async () => {
    await api.markAllNotificationsRead();
    setItems((current) => current.map((item) => ({ ...item, read: true })));
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    else if (page === "settings") navigate("/settings");
    else if (page === "vault") navigate("/vault");
    else if (page === "skills") navigate("/skills");
    else if (page === "scheduler") navigate("/scheduler");
    else if (page === "mcps") navigate("/mcps");
    else if (page === "channels") navigate("/channels");
    else if (page === "observability") navigate("/observability");
    else if (page === "traces") navigate("/traces");
    else if (page === "notifications") navigate("/notifications");
  };

  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    window.location.assign("/login");
  };

  const unread = items.filter((item) => !item.read).length;
  const visibleItems = filter === "unread" ? items.filter((item) => !item.read) : items;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="notifications"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((value) => !value)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <PageHeader icon={Bell} title="Notifications" description="Updates and actions from your local CaberOS workspace" />
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-6xl">
            <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-center gap-1">
                {(["all", "unread"] as Filter[]).map((value) => (
                  <button key={value} type="button" onClick={() => setFilter(value)} className="rounded-[4px] px-3 py-1.5 text-[12px] font-medium capitalize transition hover:bg-[var(--border)]" style={{ background: filter === value ? "var(--ink)" : "transparent", color: filter === value ? "var(--white)" : "var(--ink-2)", cursor: "pointer" }}>
                    {value} {value === "unread" && <span className="font-mono">({unread})</span>}
                  </button>
                ))}
              </div>
              {unread > 0 && <button type="button" onClick={() => void markAllRead()} className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:text-[var(--ink)]" style={{ cursor: "pointer" }}><Check className="h-3.5 w-3.5" /> Mark all as read</button>}
            </div>

            {loading ? (
              <div className="py-12 text-center text-[13px] text-[var(--ink-3)]">Loading notifications…</div>
            ) : visibleItems.length === 0 ? (
              <div className="py-16 text-center">
                <Bell className="mx-auto h-7 w-7 text-[var(--ink-3)]" />
                <h2 className="mt-3 text-[15px] font-semibold text-[var(--ink)]">{filter === "unread" ? "No unread notifications" : "You’re all caught up"}</h2>
                <p className="mt-1 text-[13px] text-[var(--ink-2)]">Important run, integration, and system updates will appear here.</p>
              </div>
            ) : (
              <div className="divide-y" style={{ borderBottom: "1px solid var(--border)" }}>
                {visibleItems.map((item) => {
                  const Icon = severityIcon[item.severity];
                  return (
                    <article key={item.id} className="flex gap-4 px-2 py-5" style={{ borderLeft: item.read ? "2px solid transparent" : "2px solid var(--accent)", opacity: item.read ? 0.62 : 1 }}>
                      <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color: severityColor[item.severity] }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-4">
                          <h2 className="text-[14px] font-medium text-[var(--ink)]">{item.title}</h2>
                          <time className="shrink-0 font-mono text-[10px] text-[var(--ink-3)]">{new Date(item.created_at).toLocaleString()}</time>
                        </div>
                        <p className="mt-1 max-w-3xl text-[13px] leading-6 text-[var(--ink-2)]">{item.message}</p>
                        <div className="mt-2 flex items-center gap-3">
                          {!item.read && <button type="button" onClick={() => void markRead(item)} className="text-[12px] font-medium text-[var(--accent)] hover:underline" style={{ cursor: "pointer" }}>Mark as read</button>}
                          {item.action_path && <button type="button" onClick={() => { void markRead(item); navigate(item.action_path!); }} className="text-[12px] font-medium text-[var(--accent)] hover:underline" style={{ cursor: "pointer" }}>Open related page</button>}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
