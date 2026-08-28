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
} from "lucide-react";
import { LogoMark } from "@/components/LogoMark";
import { NotificationCenter } from "@/components/NotificationCenter";

export type NavKey =
  | "agents"
  | "scheduler"
  | "mcps"
  | "skills"
  | "channels"
  | "vault"
  | "observability"
  | "traces"
  | "settings";

interface DashboardSidebarProps {
  active: NavKey;
  onNavigate: (page: NavKey) => void;
  onLogout: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  agentCount?: number;
}

interface NavItem {
  key: NavKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
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
  agentCount,
}: DashboardSidebarProps) {
  const sections: NavSection[] = [
    {
      label: "Workspace",
      items: [
        { key: "agents", label: "Agents", icon: Bot, badge: agentCount },
        { key: "scheduler", label: "Scheduler", icon: CalendarClock },
      ],
    },
    {
      label: "Capabilities",
      items: [
        { key: "mcps", label: "MCPs", icon: Plug },
        { key: "skills", label: "Skills", icon: Sparkles },
        { key: "channels", label: "Channels", icon: Radio },
        { key: "vault", label: "Knowledge Vault", icon: Database },
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

  // Collapsed strip — icons only
  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center gap-2 py-3"
        style={{
          width: 48,
          minWidth: 48,
          background: "var(--sidebar)",
          borderRight: "1px solid var(--border)",
        }}
      >
        <button
          onClick={onToggleCollapse}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}
          title="Expand sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
        <div style={{ borderBottom: "1px solid var(--border)", width: 28 }} />
        {sections.flatMap((s) => s.items).map((item) => {
          const Icon = item.icon;
          const isActive = active === item.key;
          return (
            <button
              key={item.key}
              onClick={() => onNavigate(item.key)}
              className="flex h-7 w-7 items-center justify-center rounded transition"
              style={{
                background: isActive ? "var(--ink)" : "none",
                color: isActive ? "var(--white)" : "var(--ink-2)",
                border: "none",
                cursor: "pointer",
              }}
              title={item.label}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = "var(--border)";
                  e.currentTarget.style.color = "var(--ink)";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = "none";
                  e.currentTarget.style.color = "var(--ink-2)";
                }
              }}
            >
              <Icon className="h-4 w-4" />
            </button>
          );
        })}
        <div className="flex-1" />
        <div className="mb-1 w-8">
          <NotificationCenter sidebar />
        </div>
        <button
          onClick={() => onNavigate("settings")}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          style={{
            background: active === "settings" ? "var(--ink)" : "none",
            color: active === "settings" ? "var(--white)" : "var(--ink-2)",
            border: "none",
            cursor: "pointer",
          }}
          title="Settings"
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
  }

  // Expanded sidebar
  return (
    <aside
      className="flex flex-col overflow-hidden border-r transition-all duration-200"
      style={{
        width: 240,
        minWidth: 240,
        background: "var(--sidebar)",
        borderColor: "var(--border)",
      }}
    >
      {/* Brand + collapse toggle */}
      <div
        className="flex items-center gap-2.5 px-4 py-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <LogoMark className="h-7 w-7 shrink-0" color="var(--brand)" />
        <span className="flex-1 text-[15px] font-semibold text-[var(--ink)]">
          CaberOS
        </span>
        <button
          onClick={onToggleCollapse}
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
                onClick={() => onNavigate(item.key)}
              />
            ))}
          </div>
        ))}
      </nav>

      {/* Footer: Settings + Sign out */}
      <div className="px-2 py-2" style={{ borderTop: "1px solid var(--border)" }}>
        <NotificationCenter sidebar />
        <NavButton
          item={{ key: "settings", label: "Settings", icon: Settings }}
          isActive={active === "settings"}
          onClick={() => onNavigate("settings")}
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
}

function NavButton({
  item,
  isActive,
  onClick,
}: {
  item: NavItem;
  isActive: boolean;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-[5px] px-2.5 py-2 text-[13px] transition"
      style={{
        background: isActive ? "var(--ink)" : "none",
        color: isActive ? "var(--white)" : "var(--ink-2)",
        fontWeight: isActive ? 500 : 400,
        border: "none",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        if (!isActive) {
          e.currentTarget.style.background = "var(--border)";
          e.currentTarget.style.color = "var(--ink)";
        }
      }}
      onMouseLeave={(e) => {
        if (!isActive) {
          e.currentTarget.style.background = "none";
          e.currentTarget.style.color = "var(--ink-2)";
        }
      }}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1 text-left">{item.label}</span>
      {item.badge != null && item.badge > 0 && (
        <span
          className="font-mono text-[11px]"
          style={{ color: isActive ? "var(--ink-3)" : "var(--ink-3)" }}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
}
