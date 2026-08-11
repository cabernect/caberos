import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarClock, Play, AlertCircle, X, Clock, Zap } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import type { HeartbeatStatus, SchedulerAlert } from "@/lib/types";

type ScheduleMode = "heartbeat" | "cron" | "event";

interface ModeDef {
  key: ScheduleMode;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  desc: string;
  available: boolean;
}

export function Scheduler() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [heartbeats, setHeartbeats] = useState<HeartbeatStatus[]>([]);
  const [alerts, setAlerts] = useState<SchedulerAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [firing, setFiring] = useState<string | null>(null);
  const [mode, setMode] = useState<ScheduleMode>("heartbeat");
  const navigate = useNavigate();

  const modes: ModeDef[] = [
    { key: "heartbeat", label: "Heartbeat", icon: CalendarClock, desc: "Periodic interval triggers", available: true },
    { key: "cron", label: "Cron", icon: Clock, desc: "Cron expression schedules", available: false },
    { key: "event", label: "Event Triggers", icon: Zap, desc: "React to external events", available: false },
  ];

  const fetchData = useCallback(async () => {
    try {
      const [hbs, alts] = await Promise.all([
        api.listHeartbeats(),
        api.listSchedulerAlerts(),
      ]);
      setHeartbeats(hbs);
      setAlerts(alts);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Poll every 10s for live status updates
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") navigate("/settings");
    if (page === "vault") navigate("/vault");
    if (page === "skills") navigate("/skills");
    if (page === "scheduler") return;
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
  };

  const handleToggle = async (agentId: string, enabled: boolean) => {
    // Optimistic update
    setHeartbeats((prev) =>
      prev.map((h) => (h.agent_id === agentId ? { ...h, enabled } : h)),
    );
    try {
      await api.updateHeartbeat(agentId, { enabled });
      fetchData();
    } catch {
      // Revert on error
      setHeartbeats((prev) =>
        prev.map((h) => (h.agent_id === agentId ? { ...h, enabled: !enabled } : h)),
      );
    }
  };

  const handleFieldChange = async (
    agentId: string,
    field: keyof HeartbeatStatus,
    value: string | number,
  ) => {
    setHeartbeats((prev) =>
      prev.map((h) => (h.agent_id === agentId ? { ...h, [field]: value } : h)),
    );
  };

  const handleFieldSave = async (
    agentId: string,
    field: "interval_minutes" | "task_prompt" | "max_cost_per_heartbeat" | "consecutive_failure_threshold",
    value: string | number,
  ) => {
    const numFields = ["interval_minutes", "max_cost_per_heartbeat", "consecutive_failure_threshold"];
    const payload: Record<string, string | number | boolean> = { [field]: value };
    if (numFields.includes(field)) {
      payload[field] = Number(value);
    }
    try {
      await api.updateHeartbeat(agentId, payload);
    } catch {
      // ignore — will refresh from server
    }
  };

  const handleFire = async (agentId: string) => {
    setFiring(agentId);
    try {
      await api.fireHeartbeat(agentId);
      fetchData();
    } catch {
      // ignore
    } finally {
      setFiring(null);
    }
  };

  const handleClearAlert = async (agentId: string) => {
    try {
      await api.clearSchedulerAlert(agentId);
      setAlerts((prev) => prev.filter((a) => a.agent_id !== agentId));
    } catch {
      // ignore
    }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="scheduler"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="px-8 py-5"
          style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
        >
          <div className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <h1 className="text-[18px] font-semibold text-[var(--ink)]">Scheduler</h1>
          </div>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
            Automate your agents with scheduled triggers
          </p>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-1 px-8 pt-4" style={{ borderBottom: "1px solid var(--border)" }}>
          {modes.map((m) => {
            const Icon = m.icon;
            const active = mode === m.key;
            return (
              <button
                key={m.key}
                onClick={() => m.available && setMode(m.key)}
                disabled={!m.available}
                className="flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition"
                style={{
                  borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                  color: active ? "var(--accent)" : m.available ? "var(--ink-2)" : "var(--ink-3)",
                  cursor: m.available ? "pointer" : "not-allowed",
                  background: "none",
                  borderTop: "none",
                  borderLeft: "none",
                  borderRight: "none",
                  opacity: m.available ? 1 : 0.5,
                }}
              >
                <Icon className="h-3.5 w-3.5" />
                {m.label}
                {!m.available && (
                  <span className="ml-1 rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase"
                    style={{ background: "var(--surface)", color: "var(--ink-3)" }}>
                    soon
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className="mx-8 mt-4 space-y-2">
            {alerts.map((alert) => (
              <div
                key={alert.agent_id}
                className="flex items-center gap-3 rounded-[6px] border px-4 py-3"
                style={{ borderColor: "var(--danger)", background: "var(--surface)" }}
              >
                <AlertCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger)" }} />
                <div className="flex-1">
                  <span className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
                    {alert.agent_name}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--ink-2)" }}>
                    {" "}
                    — heartbeat failed {alert.consecutive_failures} times (threshold: {alert.threshold})
                  </span>
                  {alert.last_error && (
                    <p className="mt-0.5 text-[11px] font-mono" style={{ color: "var(--ink-3)" }}>
                      {alert.last_error.substring(0, 120)}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => handleClearAlert(alert.agent_id)}
                  className="rounded-[4px] p-1 transition hover:bg-[var(--surface)]"
                  style={{ border: "1px solid var(--border)", cursor: "pointer" }}
                >
                  <X className="h-3.5 w-3.5" style={{ color: "var(--ink-2)" }} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {mode === "heartbeat" && (
            <>
              <p className="mb-4 text-[13px] text-[var(--ink-2)]">
                {modes.find((m) => m.key === "heartbeat")?.desc} — your agent runs autonomously at a fixed interval
              </p>
              {loading ? (
                <div className="flex h-full items-center justify-center">
                  <p className="text-[14px] text-[var(--ink-3)]">Loading…</p>
                </div>
              ) : heartbeats.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center">
                  <CalendarClock className="h-12 w-12" style={{ color: "var(--ink-3)" }} />
                  <p className="mt-4 text-[14px] text-[var(--ink-2)]">No agents found</p>
                  <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                    Create an agent first, then configure its heartbeat here.
                  </p>
                </div>
              ) : (
                <div className="mx-auto max-w-3xl space-y-4">
                  {heartbeats.map((hb) => (
                    <HeartbeatCard
                      key={hb.agent_id}
                      hb={hb}
                      firing={firing === hb.agent_id}
                      onToggle={() => handleToggle(hb.agent_id, !hb.enabled)}
                      onFieldChange={handleFieldChange}
                      onFieldSave={handleFieldSave}
                      onFire={() => handleFire(hb.agent_id)}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {mode === "cron" && (
            <ComingSoon
              icon={Clock}
              title="Cron Schedules"
              desc="Schedule agents with cron expressions — e.g. '0 9 * * 1-5' for every weekday at 9 AM. More flexible than heartbeat for non-uniform intervals."
            />
          )}

          {mode === "event" && (
            <ComingSoon
              icon={Zap}
              title="Event Triggers"
              desc="React to external events — incoming emails, webhook payloads, file changes, or signals from other agents. Connectors fire triggers automatically."
            />
          )}
        </div>
      </div>
    </div>
  );
}

function HeartbeatCard({
  hb,
  firing,
  onToggle,
  onFieldChange,
  onFieldSave,
  onFire,
}: {
  hb: HeartbeatStatus;
  firing: boolean;
  onToggle: () => void;
  onFieldChange: (agentId: string, field: keyof HeartbeatStatus, value: string | number) => void;
  onFieldSave: (
    agentId: string,
    field: "interval_minutes" | "task_prompt" | "max_cost_per_heartbeat" | "consecutive_failure_threshold",
    value: string | number,
  ) => void;
  onFire: () => void;
}) {
  const hasFailures = hb.consecutive_failures > 0;
  const statusColor =
    hb.last_status === "completed"
      ? "var(--success)"
      : hb.last_status === "failed"
        ? "var(--danger)"
        : "var(--ink-3)";

  return (
    <div
      className="rounded-[8px] border p-4"
      style={{
        borderColor: hb.enabled ? "var(--accent)" : "var(--border)",
        background: "var(--white)",
      }}
    >
      {/* Header row */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          className="relative h-5 w-9 rounded-full transition"
          style={{
            background: hb.enabled ? "#6A8216" : "#E0DFDC",
            cursor: "pointer",
            border: "none",
          }}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
            style={{ left: hb.enabled ? "18px" : "2px" }}
          />
        </button>
        <span className="text-[14px] font-medium" style={{ color: "var(--ink)" }}>
          {hb.agent_name}
        </span>
        {hb.enabled && (
          <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--accent)" }}>
            active
          </span>
        )}
        <div className="ml-auto flex items-center gap-3">
          {/* Status indicator */}
          {hb.last_status && (
            <span className="font-mono text-[11px]" style={{ color: statusColor }}>
              {hb.last_status}
            </span>
          )}
          {hasFailures && (
            <span
              className="font-mono text-[11px] rounded-full px-2 py-0.5"
              style={{ background: "var(--surface)", color: "var(--danger)" }}
            >
              {hb.consecutive_failures} fail
            </span>
          )}
          {/* Fire now button */}
          <button
            onClick={onFire}
            disabled={firing || !hb.task_prompt.trim()}
            className="flex items-center gap-1 rounded-[4px] px-2 py-1 font-mono text-[11px] transition"
            style={{
              border: "1px solid var(--border)",
              background: "var(--white)",
              color: "var(--ink-2)",
              cursor: firing || !hb.task_prompt.trim() ? "not-allowed" : "pointer",
              opacity: firing || !hb.task_prompt.trim() ? 0.5 : 1,
            }}
          >
            <Play className="h-3 w-3" />
            {firing ? "Running…" : "Fire now"}
          </button>
        </div>
      </div>

      {/* Config fields — only show when enabled */}
      {hb.enabled && (
        <div className="mt-4 space-y-3">
          {/* Task prompt */}
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              Task prompt
            </label>
            <textarea
              value={hb.task_prompt}
              onChange={(e) => onFieldChange(hb.agent_id, "task_prompt", e.target.value)}
              onBlur={(e) => onFieldSave(hb.agent_id, "task_prompt", e.target.value)}
              rows={2}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] leading-[1.5]"
              style={{
                borderColor: "var(--border)",
                background: "var(--surface)",
                color: "var(--ink)",
                resize: "vertical",
              }}
              placeholder="e.g. Check my inbox and summarize important messages"
            />
          </div>

          {/* Numeric fields */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Interval (min)
              </label>
              <input
                type="number"
                min={1}
                value={hb.interval_minutes}
                onChange={(e) => onFieldChange(hb.agent_id, "interval_minutes", Number(e.target.value))}
                onBlur={(e) => onFieldSave(hb.agent_id, "interval_minutes", e.target.value)}
                className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Max cost ($)
              </label>
              <input
                type="number"
                step={0.05}
                min={0}
                value={hb.max_cost_per_heartbeat}
                onChange={(e) => onFieldChange(hb.agent_id, "max_cost_per_heartbeat", Number(e.target.value))}
                onBlur={(e) => onFieldSave(hb.agent_id, "max_cost_per_heartbeat", e.target.value)}
                className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Fail threshold
              </label>
              <input
                type="number"
                min={1}
                value={hb.consecutive_failure_threshold}
                onChange={(e) => onFieldChange(hb.agent_id, "consecutive_failure_threshold", Number(e.target.value))}
                onBlur={(e) => onFieldSave(hb.agent_id, "consecutive_failure_threshold", e.target.value)}
                className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
          </div>

          {/* Runtime status */}
          <div className="flex gap-6 border-t pt-3" style={{ borderColor: "var(--border)" }}>
            <div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">Last fired</span>
              <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
                {hb.last_fired ? new Date(hb.last_fired).toLocaleString() : "—"}
              </p>
            </div>
            <div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">Next fire</span>
              <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
                {hb.next_fire ? new Date(hb.next_fire).toLocaleString() : "—"}
              </p>
            </div>
            {hb.last_error && (
              <div className="flex-1">
                <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">Last error</span>
                <p className="truncate text-[12px]" style={{ color: "var(--danger)" }} title={hb.last_error}>
                  {hb.last_error.substring(0, 80)}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ComingSoon({
  icon: Icon,
  title,
  desc,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  desc: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center py-20">
      <div
        className="flex h-14 w-14 items-center justify-center rounded-full"
        style={{ background: "var(--surface)" }}
      >
        <Icon className="h-6 w-6" style={{ color: "var(--ink-3)" }} />
      </div>
      <h3 className="mt-4 text-[16px] font-semibold text-[var(--ink)]">{title}</h3>
      <p className="mt-2 max-w-md text-center text-[13px] leading-[1.6] text-[var(--ink-2)]">
        {desc}
      </p>
      <span
        className="mt-4 rounded-full px-3 py-1 font-mono text-[11px] uppercase tracking-wider"
        style={{ background: "var(--surface)", color: "var(--ink-3)" }}
      >
        Planned for v0.5
      </span>
    </div>
  );
}
