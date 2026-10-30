import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bell,
  Check,
  CircleAlert,
  CircleCheck,
  Info,
  Settings2,
  TriangleAlert,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { notificationTarget } from "@/lib/notificationLinks";
import {
  refreshNotifications,
  useNotifications,
  useNotificationsLoading,
} from "@/lib/notificationStore";
import type { Notification, NotificationPrefs } from "@/lib/types";

const severityIcon = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  error: CircleAlert,
} as const;

const severityTile = {
  info: "bg-sunken text-ink-muted",
  success: "bg-accent-tint text-accent",
  warning: "bg-warning-tint text-warning",
  error: "bg-danger-tint text-danger",
} as const;

type Filter = "all" | "action" | "unread";

const PAGE_SIZE = 50;

function isActionable(item: Notification): boolean {
  return !item.read && Boolean(item.action_path || item.entity_type);
}

function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function NotificationRow({
  item,
  onOpen,
  onDismiss,
}: {
  item: Notification;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  const Icon = severityIcon[item.severity];
  return (
    <article className={`flex gap-3 px-4 py-4 ${item.read ? "opacity-60" : ""}`}>
      <span
        className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${severityTile[item.severity]}`}
      >
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-[14px] font-semibold leading-5 text-ink">
            {item.title}
            {item.agent_name && (
              <span className="ml-2 rounded bg-sunken px-1.5 py-0.5 align-middle text-[11px] font-normal text-ink-muted">
                {item.agent_name}
              </span>
            )}
          </h2>
          <time className="shrink-0 text-[12px] text-ink-faint">
            {relTime(item.created_at)}
          </time>
        </div>
        <p className="mt-0.5 text-[13px] leading-[18px] text-ink-muted">
          {item.message}
        </p>
        <div className="mt-2 flex items-center gap-3">
          {(item.action_path || item.entity_type) && (
            <button
              type="button"
              onClick={onOpen}
              className="text-[13px] font-medium text-accent hover:underline"
            >
              Open
            </button>
          )}
          {!item.read && (
            <button
              type="button"
              onClick={onDismiss}
              className="text-[13px] font-medium text-ink-muted hover:text-ink"
            >
              Mark as read
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export function Notifications() {
  const items = useNotifications();
  const loading = useNotificationsLoading();
  const [filter, setFilter] = useState<Filter>("all");
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [older, setOlder] = useState<Notification[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [shown, setShown] = useState(PAGE_SIZE);
  const navigate = useNavigate();

  useEffect(() => {
    api.getNotificationPrefs().then(setPrefs).catch(() => {});
  }, []);

  // Store holds the newest page (live SSE entries included); `older` is the
  // cursor-fetched archive appended on scroll.
  const allItems = useMemo(() => {
    const seen = new Set(items.map((i) => i.id));
    return [...items, ...older.filter((o) => !seen.has(o.id))];
  }, [items, older]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    const oldest = allItems[allItems.length - 1];
    if (!oldest) return;
    setLoadingMore(true);
    try {
      const page = await api.listNotificationsPage({
        before: oldest.created_at,
        beforeId: oldest.id,
        limit: 50,
      });
      setOlder((prev) => [...prev, ...page]);
      if (page.length < 50) setHasMore(false);
    } catch {
      // keep hasMore — the button stays so the load can be retried
    }
    setLoadingMore(false);
  }, [allItems, hasMore, loadingMore]);

  const markRead = async (item: Notification) => {
    if (item.read) return;
    await api.markNotificationRead(item.id);
    // Backend publishes inbox_changed post-commit; the explicit refresh
    // covers older backends and gives an immediate row update.
    refreshNotifications(400);
  };

  const markAllRead = async () => {
    await api.markAllNotificationsRead();
    refreshNotifications(400);
  };

  const handleNavigate = (page: NavKey) => {
    navigate(NAV_ROUTES[page]);
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  const unread = allItems.filter((item) => !item.read).length;
  const actionable = allItems.filter(isActionable);
  const visibleItems =
    filter === "unread"
      ? allItems.filter((item) => !item.read)
      : filter === "action"
        ? actionable
        : allItems;

  // Render window: show PAGE_SIZE rows at a time — buffered items reveal
  // instantly, then the button starts fetching older pages.
  const displayItems = visibleItems.slice(0, shown);
  const moreAvailable = shown < visibleItems.length || hasMore;
  const handleShowMore = async () => {
    if (shown >= visibleItems.length) await loadMore();
    setShown((s) => s + PAGE_SIZE);
  };

  const needsAction = displayItems.filter(isActionable);
  const earlier = displayItems.filter((item) => !isActionable(item));

  const alertsOn = prefs?.defaults
    ? prefs.defaults.toast || prefs.defaults.browser || prefs.defaults.system
    : null;
  const quietOn = prefs?.quiet_hours?.enabled ?? null;

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="notifications"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((value) => !value)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Observability" }, { label: "Notifications" }]}
          title="Notifications"
          subtitle="What your agents need from you, and what they finished."
          actions={
            <Button
              variant="secondary"
              onClick={() => void markAllRead()}
              disabled={unread === 0}
            >
              <Check />Mark all as read
            </Button>
          }
        />

        <div className="px-8 pb-4">
          <div className="flex flex-wrap items-center gap-3">
            <FilterPills
              pills={[
                { key: "all", label: "All" },
                { key: "action", label: "Needs action", count: actionable.length },
                { key: "unread", label: "Unread", count: unread },
              ]}
              active={filter}
              onChange={(k) => setFilter(k as Filter)}
              variant="segmented"
            />
            <div className="ml-auto">
              <Button variant="secondary" onClick={() => navigate("/settings")}>
                <Settings2 />Notification settings
              </Button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-8 pb-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="space-y-4 lg:col-span-2">
              {loading ? (
                <p className="py-20 text-center text-[14px] text-ink-faint">
                  Loading notifications…
                </p>
              ) : visibleItems.length === 0 ? (
                <EmptyState
                  icon={Bell}
                  title={
                    filter === "unread"
                      ? "No unread notifications"
                      : filter === "action"
                        ? "Nothing needs you"
                        : "You’re all caught up"
                  }
                >
                  Important run, integration, and system updates will appear here.
                </EmptyState>
              ) : (
                <>
                  {needsAction.length > 0 && (
                    <SectionCard
                      title="Needs your action"
                      bodyClassName="p-0"
                    >
                      <div className="divide-y divide-line">
                        {needsAction.map((item) => (
                          <div
                            key={item.id}
                            className="bg-warning-tint/40 first:rounded-t-[inherit]"
                          >
                            <NotificationRow
                              item={item}
                              onOpen={() => {
                                void markRead(item);
                                navigate(notificationTarget(item));
                              }}
                              onDismiss={() => void markRead(item)}
                            />
                          </div>
                        ))}
                      </div>
                    </SectionCard>
                  )}
                  {earlier.length > 0 && (
                    <SectionCard
                      title={needsAction.length > 0 ? "Earlier" : "All notifications"}
                      bodyClassName="p-0"
                    >
                      <div className="divide-y divide-line">
                        {earlier.map((item) => (
                          <NotificationRow
                            key={item.id}
                            item={item}
                            onOpen={() => {
                              void markRead(item);
                              navigate(notificationTarget(item));
                            }}
                            onDismiss={() => void markRead(item)}
                          />
                        ))}
                      </div>
                    </SectionCard>
                  )}
                  {moreAvailable ? (
                    <div className="py-2 text-center">
                      <Button
                        variant="secondary"
                        onClick={() => void handleShowMore()}
                        disabled={loadingMore}
                      >
                        {loadingMore ? "Loading…" : "Load earlier notifications"}
                      </Button>
                    </div>
                  ) : (
                    allItems.length > 0 && (
                      <p className="py-3 text-center text-[12px] text-ink-faint">
                        That's everything.
                      </p>
                    )
                  )}
                </>
              )}
            </div>

            {/* Delivery rail — surfaces + quiet hours status */}
            <aside>
              <SectionCard title="Alerts right now" bodyClassName="p-0">
                <p className="border-b border-line px-4 py-3 text-[13px] text-ink-muted">
                  What reaches you outside this inbox.
                </p>
                <div className="divide-y divide-line px-4">
                  <div className="flex items-center justify-between py-3 text-[13px]">
                    <span className="text-ink">Toasts and browser alerts</span>
                    <span className={alertsOn ? "font-medium text-ink" : "text-ink-faint"}>
                      {alertsOn === null ? "…" : alertsOn ? "On" : "Off"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-3 text-[13px]">
                    <span className="text-ink">Quiet hours</span>
                    <span className={quietOn ? "font-medium text-ink" : "text-ink-faint"}>
                      {quietOn === null
                        ? "…"
                        : quietOn
                          ? `${prefs?.quiet_hours.start}–${prefs?.quiet_hours.end}`
                          : "Off"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-3 text-[13px]">
                    <span className="text-ink">Inbox</span>
                    <span className="font-medium text-ink">Records everything</span>
                  </div>
                </div>
                <div className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => navigate("/settings")}
                    className="text-[13px] font-medium text-accent hover:underline"
                  >
                    Change in Settings
                  </button>
                </div>
              </SectionCard>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}
