import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  Bot,
  CalendarClock,
  Database,
  GitBranch,
  House,
  Plug,
  Radio,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { cn } from "@/lib/utils";

export const OPEN_PALETTE_EVENT = "caberos:command-palette";

interface PaletteItem {
  key: string;
  label: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
  path: string;
}

const PAGE_ITEMS: PaletteItem[] = [
  { key: "today", label: "Today", hint: "Home", icon: House, path: "/" },
  { key: "agents", label: "Agents", hint: "Workspace", icon: Bot, path: "/agents" },
  { key: "scheduler", label: "Scheduler", hint: "Workspace", icon: CalendarClock, path: "/scheduler" },
  { key: "mcps", label: "MCPs", hint: "Capabilities", icon: Plug, path: "/mcps" },
  { key: "skills", label: "Skills", hint: "Capabilities", icon: Sparkles, path: "/skills" },
  { key: "channels", label: "Channels", hint: "Capabilities", icon: Radio, path: "/channels" },
  { key: "vault", label: "Knowledge Vault", hint: "Capabilities", icon: Database, path: "/vault" },
  { key: "observability", label: "Overview", hint: "Observability", icon: Activity, path: "/observability" },
  { key: "traces", label: "Traces", hint: "Observability", icon: GitBranch, path: "/traces" },
  { key: "settings", label: "Settings", hint: "", icon: Settings, path: "/settings" },
];

/**
 * Minimal ⌘K palette (W13 v1): pages + agent chats. Opens on ⌘K / Ctrl+K
 * or the `caberos:command-palette` window event (the Today command bar).
 */
export function CommandPalette() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    const onEvent = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onEvent);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    api.listAgents().then(setAgents).catch(() => setAgents([]));
    // focus after mount
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  const items = useMemo(() => {
    const agentItems: PaletteItem[] = agents.map((a) => ({
      key: `agent-${a.id}`,
      label: a.name,
      hint: "Agent",
      icon: Bot,
      path: `/agents/${a.id}/chat`,
    }));
    const q = query.trim().toLowerCase();
    const all = [...PAGE_ITEMS, ...agentItems];
    if (!q) return all;
    return all.filter((i) => i.label.toLowerCase().includes(q) || i.hint.toLowerCase().includes(q));
  }, [agents, query]);

  const pick = useCallback(
    (item: PaletteItem) => {
      setOpen(false);
      navigate(item.path);
    },
    [navigate],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[15vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-md border border-line bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search className="h-4 w-4 shrink-0 text-ink-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter" && items[cursor]) {
                pick(items[cursor]);
              }
            }}
            placeholder="Search or run a command…"
            className="h-11 w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-faint"
          />
          <kbd className="shrink-0 rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
            esc
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-1.5">
          {items.length === 0 && (
            <div className="px-4 py-6 text-center text-[13px] text-ink-muted">
              Nothing matches “{query}”.
            </div>
          )}
          {items.map((item, i) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => pick(item)}
                onMouseEnter={() => setCursor(i)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-3 px-4 py-2 text-left text-[14px] transition-colors",
                  i === cursor ? "bg-sunken" : "",
                )}
              >
                <Icon className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="flex-1 text-ink">{item.label}</span>
                {item.hint && <span className="text-[12px] text-ink-faint">{item.hint}</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
