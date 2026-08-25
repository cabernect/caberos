import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Plus, MessageSquare, ArrowRight, Settings } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent, Provider } from "@/lib/types";
import {
  DashboardSidebar,
  type NavKey,
} from "@/components/DashboardSidebar";
import { CreateAgentModal } from "@/components/CreateAgentModal";
import { SettingsOverlay } from "@/components/SettingsOverlay";

interface AgentWithActivity extends Agent {
  sessionCount: number;
  lastActivity: string | null;
  messageCount: number;
}

export function AgentList() {
  const [agents, setAgents] = useState<AgentWithActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsAgent, setSettingsAgent] = useState<Agent | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const navigate = useNavigate();

  const loadAgents = useCallback(async () => {
    try {
      const list = await api.listAgents();
      const enriched = await Promise.all(
        list.map(async (a) => {
          try {
            const sessions = await api.listSessions(a.id);
            const totalMessages = sessions.reduce(
              (sum, s) => sum + (s.message_count || 0),
              0,
            );
            const lastActivity =
              sessions.length > 0
                ? sessions
                    .map((s) => s.last_activity_at)
                    .sort()
                    .reverse()[0]
                : null;
            return {
              ...a,
              sessionCount: sessions.length,
              lastActivity,
              messageCount: totalMessages,
            };
          } catch {
            return {
              ...a,
              sessionCount: 0,
              lastActivity: null,
              messageCount: 0,
            };
          }
        }),
      );
      setAgents(enriched);
    } catch {
      navigate("/login");
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  const loadProviders = useCallback(async () => {
    try {
      setProviders(await api.listProviders());
    } catch {}
  }, []);

  useEffect(() => {
    loadAgents();
    loadProviders();
  }, [loadAgents, loadProviders]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") navigate("/settings");
    if (page === "vault") navigate("/vault");
    if (page === "skills") navigate("/skills");
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="agents"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        agentCount={agents.length}
      />

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="flex items-center justify-between px-8 py-5"
          style={{
            background: "var(--sidebar)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div className="flex items-center gap-3">
            <Bot className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <div>
              <h1 className="text-[18px] font-semibold text-[var(--ink)]">
                Agents
              </h1>
              <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
                {loading
                  ? "Loading…"
                  : `${agents.length} agent${agents.length === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] font-medium transition"
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
            New Agent
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[180px] animate-pulse rounded-lg border"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--white)",
                  }}
                />
              ))}
            </div>
          ) : agents.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onClick={() => navigate(`/agents/${agent.id}/chat`)}
                  onSettings={() => {
                    setSettingsAgent(agent);
                    setShowSettings(true);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <CreateAgentModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(id) => {
          setShowCreate(false);
          loadAgents();
          navigate(`/agents/${id}/chat`);
        }}
        providers={providers}
      />

      <SettingsOverlay
        agent={settingsAgent}
        open={showSettings}
        onClose={() => setShowSettings(false)}
        onSaved={() => loadAgents()}
        providers={providers}
      />
    </div>
  );
}

function AgentCard({
  agent,
  onClick,
  onSettings,
}: {
  agent: AgentWithActivity;
  onClick: () => void;
  onSettings: () => void;
}) {
  const statusLabel = agent.enabled ? "Active" : "Disabled";
  const statusColor = agent.enabled ? "var(--success)" : "var(--ink-3)";
  const lastActivityLabel = agent.lastActivity
    ? formatRelativeTime(agent.lastActivity)
    : "No activity";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      className="group flex cursor-pointer flex-col rounded-lg border p-5 transition"
      style={{
        borderColor: "var(--border)",
        background: "var(--white)",
        opacity: agent.enabled ? 1 : 0.7,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--accent)";
        e.currentTarget.style.boxShadow = "0 2px 8px rgba(61, 82, 213, 0.08)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--border)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Top: avatar + name + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px]"
            style={{ background: "var(--accent-bg)" }}
          >
            <Bot className="h-5 w-5" style={{ color: "var(--accent)" }} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-semibold text-[var(--ink)]">
              {agent.name}
            </h3>
            <p
              className="mt-0.5 truncate font-mono text-[11px]"
              style={{
                color: agent.model ? "var(--ink-2)" : "var(--accent)",
              }}
            >
              {agent.model || "⚠ no model — configure in Settings"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: statusColor }}
          />
          <span
            className="font-mono text-[10px] uppercase tracking-wide"
            style={{ color: statusColor }}
          >
            {statusLabel}
          </span>
        </div>
      </div>

      {/* Middle: soul snippet */}
      <p className="mt-4 line-clamp-2 text-[13px] leading-[1.5] text-[var(--ink-2)]">
        {agent.soul || "No soul configured."}
      </p>

      {/* Bottom: stats + actions */}
      <div className="mt-4 flex items-center justify-between border-t pt-3" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-4">
          <Stat
            icon={<MessageSquare className="h-3.5 w-3.5" />}
            value={agent.sessionCount}
            label="sessions"
          />
          <span className="font-mono text-[11px] text-[var(--ink-3)]">
            {lastActivityLabel}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSettings();
            }}
            className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-3)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
            style={{ border: "none", background: "none", cursor: "pointer" }}
            title="Settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </button>
          <ArrowRight
            className="h-4 w-4 text-[var(--ink-3)] transition group-hover:text-[var(--accent)]"
          />
        </div>
      </div>
    </div>
  );
}

function Stat({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ color: "var(--ink-3)" }}>{icon}</span>
      <span className="font-mono text-[11px] text-[var(--ink-2)]">
        {value} {label}
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-2xl"
        style={{ background: "var(--accent-bg)" }}
      >
        <Bot className="h-8 w-8" style={{ color: "var(--accent)" }} />
      </div>
      <h3 className="text-[20px] font-semibold text-[var(--ink)]">
        No agents yet
      </h3>
      <p className="text-[13px] text-[var(--ink-2)]">
        Create your first agent to get started.
      </p>
      <button
        className="mt-2 flex items-center gap-1.5 rounded-[6px] px-4 py-2.5 text-[14px] font-medium transition"
        style={{
          background: "var(--accent)",
          color: "var(--white)",
          border: "none",
          cursor: "pointer",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.9")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        <Plus className="h-4 w-4" />
        Create Agent
      </button>
    </div>
  );
}

function formatRelativeTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
