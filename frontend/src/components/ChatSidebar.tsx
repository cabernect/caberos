import { useState } from "react";
import {
  ArrowLeft,
  Loader2,
  PanelLeft,
  Plus,
  Search,
  Settings,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock } from "@/lib/time";
import { modShortcut } from "@/lib/platform";
import { useLearningSessions } from "@/lib/sessionActivity";
import type { SessionInfo } from "@/lib/types";

interface ChatSidebarProps {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  runningSessionIds: Set<string>;
  collapsed: boolean;
  /** Agent display name for the "← Agents / {name}" breadcrumb. */
  agentName?: string;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onOpenSettings: () => void;
  onBackToAgents: () => void;
  /** Collapse the sidebar to the icon rail. */
  onCollapse: () => void;
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  runningSessionIds,
  collapsed,
  agentName,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onOpenSettings,
  onBackToAgents,
  onCollapse,
}: ChatSidebarProps) {
  const [query, setQuery] = useState("");

  if (collapsed) return null;

  const filtered = query.trim()
    ? sessions.filter((s) =>
        s.title.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : sessions;

  return (
    <aside className="chat-sidebar flex w-[260px] min-w-[260px] flex-col overflow-hidden border-r border-line bg-ground">
      {/* Breadcrumb: ← Agents / {name} + collapse toggle (top-right) */}
      <div className="flex items-center justify-between px-3.5 pb-1 pt-3.5">
        <button
          onClick={onBackToAgents}
          className="flex cursor-pointer items-center gap-1.5 text-left text-[13px] text-ink-muted transition-colors hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>
            Agents
            {agentName && (
              <span className="text-ink">
                {" / "}
                <span className="font-medium">{agentName}</span>
              </span>
            )}
          </span>
        </button>
        <button
          onClick={onCollapse}
          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-[7px] text-ink-faint transition-colors hover:bg-surface hover:text-ink"
          title="Hide sidebar"
          aria-label="Hide sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      </div>

      {/* New chat */}
      <div className="px-3 pb-2.5 pt-2">
        <button
          onClick={onNewChat}
          className="flex w-full cursor-pointer items-center gap-2 rounded-[8px] bg-ink px-3 py-2 text-[13px] font-medium text-surface transition-opacity hover:opacity-85"
        >
          <Plus className="h-4 w-4" />
          <span>New chat</span>
        </button>
      </div>

      {/* Search chats */}
      <div className="px-3 pb-1">
        <div className="flex h-[32px] items-center gap-2 rounded-[8px] border border-line bg-surface px-2.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-faint"
          />
          <kbd className="shrink-0 font-mono text-[10px] text-ink-faint">{modShortcut("/")}</kbd>
        </div>
      </div>

      {/* Session list */}
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {filtered.length === 0 ? (
          <p className="px-2 py-4 text-center text-[13px] text-ink-faint">
            {sessions.length === 0 ? (
              <>
                No conversations yet.
                <br />
                Start a new chat!
              </>
            ) : (
              "No chats match."
            )}
          </p>
        ) : (
          <SessionList
            sessions={filtered}
            activeSessionId={activeSessionId}
            runningSessionIds={runningSessionIds}
            onSelect={onSelectSession}
            onDelete={onDeleteSession}
          />
        )}
      </nav>

      {/* Footer: Chat settings */}
      <div className="border-t border-line px-2 py-2">
        <button
          onClick={onOpenSettings}
          className="flex w-full cursor-pointer items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
        >
          <Settings className="h-4 w-4 shrink-0" />
          <span>Chat settings</span>
        </button>
      </div>
    </aside>
  );
}

function SessionList({
  sessions,
  activeSessionId,
  runningSessionIds,
  onSelect,
  onDelete,
}: {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  runningSessionIds: Set<string>;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const groups = groupSessionsByDate(sessions);

  return (
    <div className="space-y-4 pb-2">
      {groups.map(([label, items]) => (
        <div key={label}>
          <div className="mb-1 px-2 text-[11px] font-medium uppercase tracking-[0.06em] text-ink-faint">
            {label}
          </div>
          {items.map((s) => (
            <SessionItem
              key={s.id}
              session={s}
              active={s.id === activeSessionId}
              running={runningSessionIds.has(s.id)}
              onSelect={() => onSelect(s.id)}
              onDelete={() => onDelete(s.id)}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

function SessionItem({
  session,
  active,
  running,
  onSelect,
  onDelete,
}: {
  session: SessionInfo;
  active: boolean;
  running: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [hovering, setHovering] = useState(false);
  const learning = useLearningSessions().has(session.id) || session.learning === true;

  const channelLabel = session.channel
    ? { telegram: "TG", zalo_bot: "Zalo", discord: "DC", zalo_oa: "Zalo OA" }[
        session.channel
      ] || session.channel
    : null;

  return (
    <div
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onClick={onSelect}
      className={cn(
        "group flex cursor-pointer items-center gap-2 truncate rounded-[8px] px-2.5 py-1.5 text-[13px] transition-colors",
        active
          ? "border border-line bg-surface font-medium text-ink"
          : "border border-transparent text-ink-muted hover:bg-sunken hover:text-ink",
      )}
    >
      {channelLabel && (
        <span className="shrink-0 rounded bg-accent-tint px-1 py-0.5 text-[9px] font-semibold uppercase text-accent">
          {channelLabel}
        </span>
      )}
      <span className="flex-1 truncate">
        {channelLabel ? session.title : `· ${session.title}`}
      </span>
      {running && !hovering && (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
      )}
      {!running && learning && !hovering && (
        <Loader2
          className="h-3.5 w-3.5 shrink-0 animate-spin text-ink-faint opacity-60"
          aria-label="Learning from this session"
        />
      )}
      {!running && !learning && !hovering && (
        <span className="shrink-0 text-[10px] tabular-nums text-ink-faint">
          {formatClock(session.last_activity_at)}
        </span>
      )}
      {hovering && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="shrink-0 cursor-pointer text-ink-faint transition-colors hover:text-danger"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function groupSessionsByDate(
  sessions: SessionInfo[],
): [string, SessionInfo[]][] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, SessionInfo[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };

  for (const s of sessions) {
    const d = new Date(s.last_activity_at);
    if (d >= today) groups["Today"].push(s);
    else if (d >= yesterday) groups["Yesterday"].push(s);
    else if (d >= weekAgo) groups["Previous 7 days"].push(s);
    else groups["Older"].push(s);
  }

  return Object.entries(groups).filter(([, items]) => items.length > 0);
}
