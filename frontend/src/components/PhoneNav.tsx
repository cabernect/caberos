import { useState } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  Bot,
  CalendarClock,
  Database,
  GitBranch,
  LogOut,
  MoreHorizontal,
  Plug,
  Radio,
  Settings,
  Sparkles,
  Bell,
  X,
} from "lucide-react";
import type { NavKey } from "@/components/DashboardSidebar";

type Icon = React.ComponentType<{ className?: string }>;

interface PhoneNavProps {
  active: NavKey;
  onNavigate: (page: NavKey) => void;
  onLogout: () => void;
}

/** The four destinations used daily get a tab; everything else lives behind "More". */
const TABS: { key: NavKey; label: string; icon: Icon }[] = [
  { key: "agents", label: "Agents", icon: Bot },
  { key: "scheduler", label: "Schedule", icon: CalendarClock },
  { key: "vault", label: "Vault", icon: Database },
  { key: "observability", label: "Activity", icon: Activity },
];

const MORE: { key: NavKey; label: string; icon: Icon }[] = [
  { key: "skills", label: "Skills", icon: Sparkles },
  { key: "mcps", label: "MCPs", icon: Plug },
  { key: "channels", label: "Channels", icon: Radio },
  { key: "traces", label: "Traces", icon: GitBranch },
  { key: "notifications", label: "Notifications", icon: Bell },
  { key: "settings", label: "Settings", icon: Settings },
];

/**
 * Phone shell: a bottom tab bar plus a "More" sheet. Rendered into document.body so it
 * floats above the page regardless of how each page lays out its own root.
 */
export function PhoneNav({ active, onNavigate, onLogout }: PhoneNavProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  const moreActive = MORE.some((item) => item.key === active);

  const go = (key: NavKey) => {
    setMoreOpen(false);
    onNavigate(key);
  };

  return createPortal(
    <>
      {moreOpen && (
        <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="More">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 cursor-default"
            style={{ background: "rgba(0,0,0,0.4)", border: "none" }}
            onClick={() => setMoreOpen(false)}
          />
          <div
            className="absolute inset-x-0 bottom-0 rounded-t-2xl px-3 pt-3"
            style={{
              background: "var(--sidebar)",
              borderTop: "1px solid var(--border)",
              paddingBottom: "calc(var(--shell-bottom) + 8px)",
            }}
          >
            <div className="mb-1 flex items-center justify-between px-2">
              <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--ink-3)]">
                More
              </span>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setMoreOpen(false)}
                className="flex h-11 w-11 items-center justify-center rounded text-[var(--ink-2)]"
                style={{ border: "none", background: "none" }}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            {MORE.map((item) => (
              <SheetRow
                key={item.key}
                icon={item.icon}
                label={item.label}
                active={active === item.key}
                onClick={() => go(item.key)}
              />
            ))}
            <SheetRow icon={LogOut} label="Sign out" onClick={onLogout} />
          </div>
        </div>
      )}

      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-[70] flex items-stretch"
        style={{
          height: "var(--shell-bottom)",
          paddingBottom: "env(safe-area-inset-bottom)",
          background: "var(--sidebar)",
          borderTop: "1px solid var(--border)",
        }}
      >
        {TABS.map((tab) => (
          <TabButton
            key={tab.key}
            icon={tab.icon}
            label={tab.label}
            active={active === tab.key && !moreOpen}
            onClick={() => go(tab.key)}
          />
        ))}
        <TabButton
          icon={MoreHorizontal}
          label="More"
          active={moreOpen || moreActive}
          onClick={() => setMoreOpen((open) => !open)}
        />
      </nav>
    </>,
    document.body,
  );
}

function TabButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: Icon;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className="flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px]"
      style={{
        border: "none",
        background: "none",
        cursor: "pointer",
        color: active ? "var(--accent)" : "var(--ink-2)",
        fontWeight: active ? 600 : 400,
      }}
    >
      <Icon className="h-5 w-5" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function SheetRow({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: Icon;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-[15px]"
      style={{
        border: "none",
        cursor: "pointer",
        background: active ? "var(--ink)" : "none",
        color: active ? "var(--white)" : "var(--ink)",
      }}
    >
      <Icon className="h-5 w-5 shrink-0" />
      <span>{label}</span>
    </button>
  );
}
