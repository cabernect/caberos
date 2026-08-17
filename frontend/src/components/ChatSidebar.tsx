import { useState } from "react";
import { Plus, Settings, Trash2, ArrowLeft, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionInfo } from "@/lib/types";

interface ChatSidebarProps {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  runningSessionIds: Set<string>;
  collapsed: boolean;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onOpenSettings: () => void;
  onBackToAgents: () => void;
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  runningSessionIds,
  collapsed,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onOpenSettings,
  onBackToAgents,
}: ChatSidebarProps) {
  if (collapsed) return null;

  return (
    <aside
      className="flex flex-col overflow-hidden border-r transition-all duration-200"
      style={{
        width: 260,
        minWidth: 260,
        background: "var(--sidebar)",
        borderColor: "var(--border)",
      }}
    >
      {/* Top: New Chat */}
      <div className="px-3 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        <button
          onClick={onNewChat}
          className="flex w-full items-center gap-2 rounded-[6px] px-3 py-2 text-[13px] font-medium transition"
          style={{
            background: "var(--ink)",
            color: "var(--white)",
            border: "1px solid var(--ink)",
            cursor: "pointer",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.85")}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
        >
          <Plus className="h-4 w-4" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Session list */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {sessions.length === 0 ? (
          <p className="px-2 py-4 text-center text-[13px] text-[var(--ink-3)]">
            No conversations yet.
            <br />
            Start a new chat!
          </p>
        ) : (
          <SessionList
            sessions={sessions}
            activeSessionId={activeSessionId}
            runningSessionIds={runningSessionIds}
            onSelect={onSelectSession}
            onDelete={onDeleteSession}
          />
        )}
      </nav>

      {/* Bottom: Settings + Back to Agents */}
      <div className="px-2 py-2" style={{ borderTop: "1px solid var(--border)" }}>
        <button
          onClick={onOpenSettings}
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
          <Settings className="h-4 w-4 shrink-0" />
          <span>Settings</span>
        </button>
        <button
          onClick={onBackToAgents}
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
          <ArrowLeft className="h-4 w-4 shrink-0" />
          <span>Back to Agents</span>
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
          <div
            className="mb-1 px-2 font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--ink-3)]"
          >
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

  return (
    <div
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onClick={onSelect}
      className={cn(
        "group flex cursor-pointer items-center gap-2 truncate rounded-[5px] px-2.5 py-1.5 text-[13px] transition",
        active
          ? "bg-[var(--ink)] font-medium text-[var(--white)]"
          : "text-[var(--ink-2)] hover:bg-[var(--border)] hover:text-[var(--ink)]",
      )}
    >
      <span className="flex-1 truncate">· {session.title}</span>
      {running && !hovering && (
        <Loader2
          className="h-3.5 w-3.5 shrink-0 animate-spin"
          style={{ color: active ? "var(--white)" : "var(--accent)" }}
        />
      )}
      {hovering && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="shrink-0 text-[var(--ink-3)] transition hover:text-[var(--danger)]"
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
