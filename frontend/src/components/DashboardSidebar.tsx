import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMediaQuery } from "@/lib/useMediaQuery";
import {
  Bot,
  CalendarClock,
  Plug,
  Sparkles,
  Radio,
  Activity,
  Settings,
  LogOut,
  PanelLeft,
  Database,
  GitBranch,
  House,
} from "lucide-react";
import { LogoMark } from "@/components/LogoMark";
import { NotificationCenter } from "@/components/NotificationCenter";
import { api, type HomeData } from "@/lib/api";
import { getStoredSidebarCollapsed, setStoredSidebarCollapsed } from "@/lib/sidebarState";

export type NavKey =
  | "today"
  | "agents"
  | "scheduler"
  | "mcps"
  | "skills"
  | "channels"
  | "vault"
  | "observability"
  | "traces"
  | "notifications"
  | "settings";

/** Canonical nav-key → path map. Pages delegate handleNavigate to this. */
export const NAV_ROUTES: Record<NavKey, string> = {
  today: "/",
  agents: "/agents",
  scheduler: "/scheduler",
  mcps: "/mcps",
  skills: "/skills",
  channels: "/channels",
  vault: "/vault",
  observability: "/observability",
  traces: "/traces",
  notifications: "/notifications",
  settings: "/settings",
};

interface DashboardSidebarProps {
  active: NavKey;
  onNavigate?: (page: NavKey) => void;
  onLogout: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** @deprecated badges come from /api/home — this prop is ignored. */
  agentCount?: number;
}

interface NavItem {
  key: NavKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

export function DashboardSidebar({
  active,
  onNavigate,
  onLogout,
  collapsed,
  onToggleCollapse,
}: DashboardSidebarProps) {
  const navigate = useNavigate();
  const [home, setHome] = useState<HomeData | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => getStoredSidebarCollapsed() ?? collapsed,
  );
  // <768: always the 48px icon strip — full nav slides over as a modal
  // layer. Desktop stored preferences are never touched.
  const isNarrow = useMediaQuery("(max-width: 767px)");
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    if (!isNarrow) setMobileOpen(false);
  }, [isNarrow]);

  const handleToggleCollapse = () => {
    if (isNarrow) {
      setMobileOpen((v) => !v);
      return;
    }
    setSidebarCollapsed((current) => {
      const next = !current;
      setStoredSidebarCollapsed(next);
      return next;
    });
    onToggleCollapse();
  };

  const navigateAndClose = (key: NavKey) => {
    setMobileOpen(false);
    if (onNavigate) onNavigate(key);
    else navigate(NAV_ROUTES[key]);
  };

  // One aggregate fetch powers every section badge + the footer card.
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .getHome(ctrl.signal)
      .then(setHome)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  const counts = home?.counts;
  // One badge semantic everywhere: "live/total" while something runs,
  // bare total when idle — the value never flips with navigation.
  const agentBadge = counts
    ? counts.agents_running > 0
      ? `${counts.agents_running}/${counts.agents_total}`
      : counts.agents_total
    : undefined;
  const sections: NavSection[] = [
    {
      label: "Workspace",
      items: [
        { key: "today", label: "Today", icon: House },
        { key: "agents", label: "Agents", icon: Bot, badge: agentBadge },
        { key: "scheduler", label: "Scheduler", icon: CalendarClock },
      ],
    },
    {
      label: "Capabilities",
      items: [
        {
          key: "mcps",
          label: "MCPs",
          icon: Plug,
          badge: counts ? `${counts.mcps_connected}/${counts.mcps_total}` : undefined,
        },
        { key: "skills", label: "Skills", icon: Sparkles, badge: counts?.skills_published },
        {
          key: "channels",
          label: "Channels",
          icon: Radio,
          badge: counts ? `${counts.channels_active}/${counts.channels_total}` : undefined,
        },
        { key: "vault", label: "Knowledge Vault", icon: Database, badge: counts?.vault_documents },
      ],
    },
    {
      label: "Observability",
      items: [
        { key: "observability", label: "Overview", icon: Activity },
        { key: "traces", label: "Traces", icon: GitBranch },
      ],
    },
  ];

  // Collapsed strip — icons only. On <768 it is ALWAYS the in-flow rail;
  // the expanded nav only ever appears as an overlay.
  const strip = (
      <div
        data-tour="sidebar"
        className="flex flex-col items-center gap-2 py-3"
        style={{
          width: 48,
          minWidth: 48,
          background: "var(--sidebar)",
          borderRight: "1px solid var(--caberos-sidebar-border)",
        }}
      >
        <button
          onClick={handleToggleCollapse}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}
          title="Expand sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
        <div style={{ borderBottom: "1px solid var(--sidebar-divider)", width: 28 }} />
        {sections.flatMap((s) => s.items).map((item) => {
          const Icon = item.icon;
          const isActive = active === item.key;
          return (
            <button
              key={item.key}
              data-nav={item.key}
              onClick={() => navigateAndClose(item.key)}
              className="flex h-7 w-7 items-center justify-center rounded transition"
              style={{
                background: isActive ? "var(--accent-tint)" : "none",
                color: isActive ? "var(--accent)" : "var(--ink-2)",
                border: "none",
                cursor: "pointer",
              }}
              title={item.label}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = isActive ? "var(--accent-tint)" : "var(--border)";
                e.currentTarget.style.color = isActive ? "var(--accent)" : "var(--ink)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = isActive ? "var(--accent-tint)" : "none";
                e.currentTarget.style.color = isActive ? "var(--accent)" : "var(--ink-2)";
              }}
            >
              <Icon className="h-4 w-4" />
            </button>
          );
        })}
        <div className="flex-1" />
        <div className="mb-1 flex w-7 justify-center" data-nav="notifications">
          <NotificationCenter sidebar collapsed active={active === "notifications"} />
        </div>
        <button
          data-nav="settings"
          onClick={() => navigateAndClose("settings")}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{
            background: active === "settings" ? "var(--accent-tint)" : "none",
            color: active === "settings" ? "var(--accent)" : "var(--ink-2)",
            border: "none",
            cursor: "pointer",
          }}
          title="Settings"
          onMouseEnter={(e) => { e.currentTarget.style.background = active === "settings" ? "var(--accent-tint)" : "var(--border)"; e.currentTarget.style.color = active === "settings" ? "var(--accent)" : "var(--ink)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = active === "settings" ? "var(--accent-tint)" : "none"; e.currentTarget.style.color = active === "settings" ? "var(--accent)" : "var(--ink-2)"; }}
        >
          <Settings className="h-4 w-4" />
        </button>
        <button
          onClick={onLogout}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
  );

  if (isNarrow ? !mobileOpen : sidebarCollapsed) return strip;

  // Expanded sidebar — a fixed overlay + scrim below 768px so the
  // content column keeps its full width.
  const expandedAside = (
    <aside
      data-tour="sidebar"
      className="flex flex-col overflow-visible border-r transition-all duration-200"
      style={{
        width: 240,
        minWidth: 240,
        background: "var(--sidebar)",
        borderColor: "var(--caberos-sidebar-border)",
        ...(isNarrow
          ? { position: "fixed" as const, top: 0, left: 0, bottom: 0, zIndex: 40 }
          : {}),
      }}
    >
      {/* Brand + collapse toggle */}
      <div
        className="flex items-center gap-2.5 px-4 py-4"
        style={{ borderBottom: "1px solid var(--sidebar-divider)" }}
      >
        <LogoMark className="h-7 w-7 shrink-0" color="var(--brand)" />
        <span className="flex-1 text-[15px] font-semibold text-[var(--ink)]">
          CaberOS
        </span>
        <button
          onClick={handleToggleCollapse}
          className="flex h-6 w-6 items-center justify-center rounded text-[var(--ink-3)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}
          title="Collapse sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      </div>

      {/* Nav sections */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {sections.map((section) => (
          <div key={section.label} className="mb-4">
            <div
              className="mb-1 px-2 font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--ink-3)]"
            >
              {section.label}
            </div>
            {section.items.map((item) => (
              <NavButton
                key={item.key}
                item={item}
                isActive={active === item.key}
                onClick={() => navigateAndClose(item.key)}
                data-nav={item.key}
              />
            ))}
          </div>
        ))}
      </nav>

      {/* Footer: local-status card + Settings + Sign out */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-2">
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
          <span className="min-w-0 flex-1 truncate text-[12px] leading-4 text-ink-muted">
            Running locally
            {counts ? ` · ${counts.mcps_connected} MCP live` : ""}
          </span>
        </div>
      </div>
      <div className="px-2 py-2" style={{ borderTop: "1px solid var(--sidebar-divider)" }}>
        <span data-nav="notifications" className="block">
          <NotificationCenter sidebar active={active === "notifications"} />
        </span>
        <NavButton
          item={{ key: "settings", label: "Settings", icon: Settings }}
          isActive={active === "settings"}
          onClick={() => navigateAndClose("settings")}
          data-nav="settings"
        />
        <button
          onClick={onLogout}
          className="flex w-full items-center gap-2.5 rounded-[5px] px-2.5 py-2 text-[13px] text-[var(--ink-2)] transition"
          style={{ border: "none", background: "none", cursor: "pointer" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--border)";
            e.currentTarget.style.color = "var(--ink)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "none";
            e.currentTarget.style.color = "var(--ink-2)";
          }}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  );

  if (isNarrow && mobileOpen) {
    return (
      <>
        {strip}
        <div
          data-testid="sidebar-scrim"
          onClick={() => setMobileOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            zIndex: 39,
          }}
        />
        {expandedAside}
      </>
    );
  }
  return expandedAside;
}

function NavButton({
  item,
  isActive,
  onClick,
  ...rest
}: {
  item: NavItem;
  isActive: boolean;
  onClick: () => void;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const Icon = item.icon;
  return (
    <button
      onClick={onClick}
      {...rest}
      className="flex w-full items-center gap-2.5 rounded-[5px] px-2.5 py-2 text-[13px] transition"
      style={{
        background: isActive ? "var(--accent-tint)" : "none",
        color: isActive ? "var(--accent)" : "var(--ink-2)",
        fontWeight: isActive ? 500 : 400,
        border: "none",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = isActive ? "var(--accent-tint)" : "var(--border)";
        e.currentTarget.style.color = isActive ? "var(--accent)" : "var(--ink)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = isActive ? "var(--accent-tint)" : "none";
        e.currentTarget.style.color = isActive ? "var(--accent)" : "var(--ink-2)";
      }}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1 text-left">{item.label}</span>
      {item.badge != null && item.badge !== 0 && item.badge !== "" && (
        <span
          className="font-mono text-[11px]"
          style={{ color: isActive ? "var(--accent)" : "var(--ink-3)" }}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
}
