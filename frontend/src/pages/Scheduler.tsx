import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  CalendarClock,
  Play,
  AlertCircle,
  X,
  Clock,
  Plus,
  Copy,
  Trash2,
  History,
  FlaskConical,
  Pencil,
  HeartPulse,
} from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";
import type {
  Agent,
  HeartbeatStatus,
  Schedule,
  ScheduleOccurrence,
  SchedulePayload,
  ScheduleTrigger,
  SchedulerAlert,
} from "@/lib/types";

const inputStyle: React.CSSProperties = {
  borderColor: "var(--border)",
  background: "var(--surface)",
  color: "var(--ink)",
};

const labelStyle: React.CSSProperties = {
  color: "var(--ink-3)",
};

const actionBtn: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--white)",
  color: "var(--ink-2)",
  cursor: "pointer",
};

const TIMEZONES: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Asia/Tokyo"];
  }
})();

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function triggerSummary(t: ScheduleTrigger | null): string {
  if (!t) return "—";
  if (t.kind === "once") return `Once — ${t.at ? new Date(t.at).toLocaleString() : "?"}`;
  if (t.kind === "interval") {
    const s = t.every_seconds ?? 0;
    if (s % 86400 === 0) return `Every ${s / 86400} day${s === 86400 ? "" : "s"}`;
    if (s % 3600 === 0) return `Every ${s / 3600} hour${s === 3600 ? "" : "s"}`;
    if (s % 60 === 0) return `Every ${s / 60} min`;
    return `Every ${s}s`;
  }
  if (t.kind === "cron") return `${describeCron(t.cron ?? "")} · ${t.timezone || "UTC"}`;
  return t.kind;
}

/** Human description for the cron presets the builder can emit; falls back to the raw expression. */
function describeCron(expr: string): string {
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return expr;
  const [m, h, dom, , dow] = p;
  const time = `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  if (dom === "*" && dow === "*") return `Every day at ${time}`;
  if (dom === "*" && dow === "1-5") return `Weekdays at ${time}`;
  if (dom === "*" && dow === "1-6") return `Mon–Sat at ${time}`;
  if (dom === "*" && dow === "0-6") return `Every day at ${time}`;
  if (dom === "*" && /^[\d,]+$/.test(dow)) {
    const days = dow.split(",").map((d) => DOW[Number(d)] ?? d);
    return `${days.join(" + ")} at ${time}`;
  }
  if (dow === "*" && /^\d+$/.test(dom)) return `Day ${dom} of each month at ${time}`;
  return expr;
}

function statusColor(status: string | null): string {
  switch (status) {
    case "completed":
      return "var(--success)";
    case "failed":
      return "var(--danger)";
    case "running":
      return "var(--accent)";
    case "cancelled":
    case "skipped_missed":
    case "skipped_overlap":
      return "var(--ink-3)";
    default:
      return "var(--ink-2)";
  }
}

export function Scheduler() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mode, setMode] = useState<"schedules" | "heartbeat">("schedules");
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [heartbeats, setHeartbeats] = useState<HeartbeatStatus[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [alerts, setAlerts] = useState<SchedulerAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [firing, setFiring] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    // Independent fetches — one failing endpoint must not blank the page
    // (e.g. an older gateway without /api/schedules still shows heartbeats).
    const [scheds, hbs, alts, agts] = await Promise.all([
      api.listSchedules().catch(() => null),
      api.listHeartbeats().catch(() => null),
      api.listSchedulerAlerts().catch(() => null),
      api.listAgents().catch(() => null),
    ]);
    if (scheds) setSchedules(scheds);
    if (hbs) setHeartbeats(hbs);
    if (alts) setAlerts(alts);
    if (agts) setAgents(agts);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
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
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  const handleToggle = async (sched: Schedule) => {
    try {
      if (sched.enabled) {
        await api.pauseSchedule(sched.id);
      } else {
        await api.resumeSchedule(sched.id);
      }
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const handleHbToggle = async (hb: HeartbeatStatus) => {
    const enabled = !hb.enabled;
    setHeartbeats((prev) =>
      prev.map((h) => (h.agent_id === hb.agent_id ? { ...h, enabled } : h)),
    );
    try {
      await api.updateHeartbeat(hb.agent_id, { enabled });
      fetchData();
    } catch (e) {
      setHeartbeats((prev) =>
        prev.map((h) => (h.agent_id === hb.agent_id ? { ...h, enabled: !enabled } : h)),
      );
      setRunError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const handleHbFieldChange = (
    agentId: string,
    field: keyof HeartbeatStatus,
    value: string | number,
  ) => {
    setHeartbeats((prev) =>
      prev.map((h) => (h.agent_id === agentId ? { ...h, [field]: value } : h)),
    );
  };

  const handleHbFieldSave = async (
    agentId: string,
    field: "interval_minutes" | "task_prompt" | "max_cost_per_heartbeat" | "consecutive_failure_threshold",
    value: string | number,
  ) => {
    const numFields = ["interval_minutes", "max_cost_per_heartbeat", "consecutive_failure_threshold"];
    const payload: Record<string, string | number | boolean> = { [field]: value };
    if (numFields.includes(field)) payload[field] = Number(value);
    try {
      await api.updateHeartbeat(agentId, payload);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Save failed");
      fetchData();
    }
  };

  const handleHbFire = async (agentId: string) => {
    setFiring(agentId);
    setRunError(null);
    try {
      const r = await api.fireHeartbeat(agentId);
      if (r.error) setRunError(r.error);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setFiring(null);
    }
  };

  const handleRun = async (id: string, test = false) => {
    setFiring(id);
    setRunError(null);
    try {
      const r = test ? await api.testRunSchedule(id) : await api.runScheduleNow(id);
      if (r.error) setRunError(r.error);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setFiring(null);
    }
  };

  const handleDuplicate = async (id: string) => {
    try {
      await api.duplicateSchedule(id);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Duplicate failed");
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteSchedule(id);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Archive failed");
    }
  };

  const handleClearAlert = async (agentId: string) => {
    try {
      await api.clearSchedulerAlert(agentId);
      setAlerts((prev) => prev.filter((a) => a.agent_id !== agentId));
    } catch {}
  };

  // User-created schedules only — managed heartbeat rows live on their own tab
  const sorted = useMemo(
    () =>
      schedules
        .filter((s) => !s.managed)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [schedules],
  );

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
        <PageHeader
          icon={CalendarClock}
          title="Scheduler"
          description="Autonomous runs for your agents — heartbeat pulse, one-time, interval, or cron"
        >
          <button
            onClick={() => setEditing("new")}
            className="ml-auto flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] font-medium transition"
            style={{
              background: "var(--ink)",
              color: "var(--white)",
              border: "1px solid var(--ink)",
              cursor: "pointer",
            }}
          >
            <Plus className="h-4 w-4" />
            New schedule
          </button>
        </PageHeader>

        {/* Surface tabs — heartbeat is its own surface, not a schedule kind */}
        <div className="flex gap-1 px-8 pt-4" style={{ borderBottom: "1px solid var(--border)" }}>
          {(
            [
              ["schedules", "Schedules", Clock],
              ["heartbeat", "Heartbeat", HeartPulse],
            ] as const
          ).map(([key, label, Icon]) => {
            const active = mode === key;
            return (
              <button
                key={key}
                onClick={() => setMode(key)}
                className="flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition"
                style={{
                  borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                  color: active ? "var(--accent)" : "var(--ink-2)",
                  cursor: "pointer",
                  background: "none",
                  borderTop: "none",
                  borderLeft: "none",
                  borderRight: "none",
                }}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            );
          })}
        </div>

        {/* Run/action errors (e.g. "Schedule has no task prompt") */}
        {runError && (
          <div className="mx-8 mt-4 flex items-center gap-3 rounded-[6px] border px-4 py-2.5" style={{ borderColor: "var(--danger)", background: "var(--surface)" }}>
            <AlertCircle className="h-4 w-4 shrink-0" style={{ color: "var(--danger)" }} />
            <span className="flex-1 text-[12px]" style={{ color: "var(--ink)" }}>{runError}</span>
            <button onClick={() => setRunError(null)} className="rounded-[4px] p-1" style={{ border: "none", background: "none", cursor: "pointer" }}>
              <X className="h-3.5 w-3.5" style={{ color: "var(--ink-2)" }} />
            </button>
          </div>
        )}

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className="mx-8 mt-4 space-y-2">
            {alerts.map((alert, i) => (
              <div
                key={`${alert.agent_id}-${i}`}
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
                    — failed {alert.consecutive_failures} times (threshold: {alert.threshold})
                  </span>
                  {alert.last_error && (
                    <p className="mt-0.5 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
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

        {/* Schedule list — user-created schedules only */}
        {mode === "schedules" && (
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {loading ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-[14px] text-[var(--ink-3)]">Loading…</p>
            </div>
          ) : sorted.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center">
              <Clock className="h-12 w-12" style={{ color: "var(--ink-3)" }} />
              <p className="mt-4 text-[14px] text-[var(--ink-2)]">No schedules yet</p>
              <p className="mt-1 max-w-sm text-center text-[12px] text-[var(--ink-3)]">
                Attach once, interval, or cron schedules to an agent — every run is an
                independent session with its own history. For the per-agent periodic
                pulse, use the Heartbeat tab.
                {agents.length === 0 && " Create an agent first."}
              </p>
              <button
                onClick={() => setEditing("new")}
                className="mt-4 flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] font-medium"
                style={{
                  background: "var(--ink)",
                  color: "var(--white)",
                  border: "1px solid var(--ink)",
                  cursor: "pointer",
                }}
              >
                <Plus className="h-4 w-4" />
                Create your first schedule
              </button>
            </div>
          ) : (
            <div className="mx-auto max-w-4xl space-y-4">
              {sorted.map((sched) => (
                <ScheduleCard
                  key={sched.id}
                  sched={sched}
                  firing={firing === sched.id}
                  historyOpen={historyFor === sched.id}
                  onToggle={() => handleToggle(sched)}
                  onRun={() => handleRun(sched.id)}
                  onTest={() => handleRun(sched.id, true)}
                  onEdit={() => setEditing(sched)}
                  onDuplicate={() => handleDuplicate(sched.id)}
                  onDelete={() => handleDelete(sched.id)}
                  onHistory={() => setHistoryFor(historyFor === sched.id ? null : sched.id)}
                />
              ))}
            </div>
          )}
        </div>
        )}

        {/* Heartbeat — the agent's built-in periodic pulse (per-agent config) */}
        {mode === "heartbeat" && (
          <div className="flex-1 overflow-y-auto px-8 py-6">
            <p className="mb-4 text-[13px]" style={{ color: "var(--ink-2)" }}>
              Each agent has one heartbeat — it fires on a fixed interval with the agent's
              own cost cap and failure-alert threshold.
            </p>
            {loading ? (
              <div className="flex h-full items-center justify-center">
                <p className="text-[14px] text-[var(--ink-3)]">Loading…</p>
              </div>
            ) : heartbeats.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center">
                <HeartPulse className="h-12 w-12" style={{ color: "var(--ink-3)" }} />
                <p className="mt-4 text-[14px]" style={{ color: "var(--ink-2)" }}>No agents found</p>
                <p className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>
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
                    onToggle={() => handleHbToggle(hb)}
                    onFieldChange={handleHbFieldChange}
                    onFieldSave={handleHbFieldSave}
                    onFire={() => handleHbFire(hb.agent_id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {editing !== null && (
        <ScheduleDialog
          schedule={editing === "new" ? null : editing}
          agents={agents}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            fetchData();
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schedule card
// ---------------------------------------------------------------------------

function ScheduleCard({
  sched,
  firing,
  historyOpen,
  onToggle,
  onRun,
  onTest,
  onEdit,
  onDuplicate,
  onDelete,
  onHistory,
}: {
  sched: Schedule;
  firing: boolean;
  historyOpen: boolean;
  onToggle: () => void;
  onRun: () => void;
  onTest: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onHistory: () => void;
}) {
  const managed = sched.managed === "heartbeat";
  const [occurrences, setOccurrences] = useState<ScheduleOccurrence[] | null>(null);

  useEffect(() => {
    if (historyOpen) {
      api
        .listScheduleOccurrences(sched.id, 20)
        .then((r) => setOccurrences(r.occurrences))
        .catch(() => setOccurrences([]));
    }
  }, [historyOpen, sched.id]);

  return (
    <div
      className="rounded-xl p-4"
      style={{
        border: sched.enabled ? "1px solid var(--accent)" : "1px solid var(--border-soft)",
        background: "var(--sidebar)",
      }}
    >
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          className="relative h-5 w-9 shrink-0 rounded-full transition"
          style={{ background: sched.enabled ? "var(--accent)" : "var(--ink-3)", cursor: "pointer", border: "none" }}
          title={sched.enabled ? "Pause" : "Resume"}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
            style={{ left: sched.enabled ? "18px" : "2px" }}
          />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[14px] font-medium" style={{ color: "var(--ink)" }}>
              {sched.name}
            </span>
            <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              {sched.agent_name}
            </span>
            {managed && (
              <span
                className="rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase"
                style={{ background: "var(--surface)", color: "var(--ink-3)" }}
              >
                heartbeat
              </span>
            )}
            <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>
              rev {sched.revision_number}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[12px]" style={{ color: "var(--ink-2)" }}>
            {triggerSummary(sched.trigger)}
            {sched.task_prompt && (
              <span className="ml-2" style={{ color: "var(--ink-3)" }}>
                — {sched.task_prompt.substring(0, 60)}
                {sched.task_prompt.length > 60 ? "…" : ""}
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {sched.last_status && (
            <span className="font-mono text-[11px]" style={{ color: statusColor(sched.last_status) }}>
              {sched.last_status}
            </span>
          )}
          {sched.consecutive_failures > 0 && (
            <span
              className="rounded-full px-2 py-0.5 font-mono text-[11px]"
              style={{ background: "var(--surface)", color: "var(--danger)" }}
            >
              {sched.consecutive_failures} fail
            </span>
          )}
          <button onClick={onRun} disabled={firing} className="flex items-center gap-1 rounded-[4px] px-2 py-1 font-mono text-[11px]" style={{ ...actionBtn, opacity: firing ? 0.5 : 1 }} title="Run now (real run)">
            <Play className="h-3 w-3" />
            {firing ? "…" : "Run"}
          </button>
          <button onClick={onTest} disabled={firing} className="flex items-center gap-1 rounded-[4px] px-2 py-1 font-mono text-[11px]" style={actionBtn} title="Test run (scripted, no model call)">
            <FlaskConical className="h-3 w-3" />
          </button>
          <button onClick={onHistory} className="rounded-[4px] px-2 py-1" style={{ ...actionBtn, color: historyOpen ? "var(--accent)" : "var(--ink-2)" }} title="Occurrence history">
            <History className="h-3 w-3" />
          </button>
          <button onClick={onEdit} className="rounded-[4px] px-2 py-1" style={actionBtn} title={managed ? "Edit heartbeat config" : "Edit"}>
            <Pencil className="h-3 w-3" />
          </button>
          <button onClick={onDuplicate} className="rounded-[4px] px-2 py-1" style={actionBtn} title="Duplicate as a new disabled schedule">
            <Copy className="h-3 w-3" />
          </button>
          <button onClick={onDelete} disabled={managed} className="rounded-[4px] px-2 py-1" style={{ ...actionBtn, color: "var(--danger)", opacity: managed ? 0.4 : 1, cursor: managed ? "not-allowed" : "pointer" }} title={managed ? "A heartbeat always exists — toggle it off instead" : "Archive"}>
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      <div className="mt-3 flex gap-6 border-t pt-3" style={{ borderColor: "var(--border)" }}>
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Next fire</span>
          <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
            {sched.next_fire_at ? new Date(sched.next_fire_at).toLocaleString() : "—"}
          </p>
        </div>
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Last fired</span>
          <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
            {sched.last_fired_at ? new Date(sched.last_fired_at).toLocaleString() : "—"}
          </p>
        </div>
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Missed / overlap</span>
          <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
            {sched.policies ? `${sched.policies.missed} / ${sched.policies.overlap}` : "—"}
          </p>
        </div>
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Retry</span>
          <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
            {sched.policies?.failure.mode === "bounded_retry"
              ? `≤${sched.policies.failure.max_attempts}× (${sched.policies.failure.backoff_seconds}s)`
              : "none"}
          </p>
        </div>
        {sched.last_error && (
          <div className="min-w-0 flex-1">
            <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Last error</span>
            <p className="truncate text-[12px]" style={{ color: "var(--danger)" }} title={sched.last_error}>
              {sched.last_error.substring(0, 80)}
            </p>
          </div>
        )}
      </div>

      {historyOpen && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>
            Occurrence history
          </span>
          {occurrences === null ? (
            <p className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>Loading…</p>
          ) : occurrences.length === 0 ? (
            <p className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>No occurrences yet</p>
          ) : (
            <div className="mt-1 max-h-64 space-y-1 overflow-y-auto">
              {occurrences.map((occ) => (
                <div
                  key={occ.id}
                  className="flex items-center gap-3 rounded-[4px] px-2 py-1.5 text-[12px]"
                  style={{ background: "var(--surface)" }}
                >
                  <span className="font-mono" style={{ color: statusColor(occ.status) }}>
                    {occ.status}
                  </span>
                  <span style={{ color: "var(--ink-2)" }}>
                    {new Date(occ.scheduled_for).toLocaleString()}
                  </span>
                  {occ.attempt > 1 && (
                    <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>
                      attempt {occ.attempt}
                    </span>
                  )}
                  {occ.run_id && (
                    <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>
                      run {occ.run_id.slice(0, 8)}
                    </span>
                  )}
                  {occ.error && (
                    <span className="ml-auto truncate font-mono text-[10px]" style={{ color: "var(--danger)" }} title={occ.error}>
                      {occ.error.substring(0, 60)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog — centered modal. Two shapes: managed heartbeat vs full schedule.
// ---------------------------------------------------------------------------

function ModalShell({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "rgba(0,0,0,0.35)" }}
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-[560px] overflow-y-auto rounded-xl p-6"
        style={{ background: "var(--sidebar)", boxShadow: "0 8px 40px rgba(0,0,0,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function ScheduleDialog({
  schedule,
  agents,
  onClose,
  onSaved,
}: {
  schedule: Schedule | null;
  agents: Agent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  return (
    <ModalShell onClose={onClose}>
      <FullScheduleForm schedule={schedule} agents={agents} onClose={onClose} onSaved={onSaved} />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Heartbeat card — per-agent pulse config, edits via the heartbeat facade API
// ---------------------------------------------------------------------------

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
  const numField = (v: string) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };

  return (
    <div
      className="rounded-xl p-4"
      style={{
        border: hb.enabled ? "1px solid var(--accent)" : "1px solid var(--border-soft)",
        background: "var(--sidebar)",
      }}
    >
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          className="relative h-5 w-9 shrink-0 rounded-full transition"
          style={{ background: hb.enabled ? "var(--accent)" : "var(--ink-3)", cursor: "pointer", border: "none" }}
          title={hb.enabled ? "Pause" : "Resume"}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
            style={{ left: hb.enabled ? "18px" : "2px" }}
          />
        </button>
        <span className="text-[14px] font-medium" style={{ color: "var(--ink)" }}>
          {hb.agent_name}
        </span>
        <span
          className="rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase"
          style={{ background: "var(--surface)", color: "var(--ink-3)" }}
        >
          heartbeat
        </span>
        <div className="ml-auto flex items-center gap-3">
          {hb.last_status && (
            <span className="font-mono text-[11px]" style={{ color: statusColor(hb.last_status) }}>
              {hb.last_status}
            </span>
          )}
          {hb.consecutive_failures > 0 && (
            <span
              className="rounded-full px-2 py-0.5 font-mono text-[11px]"
              style={{ background: "var(--surface)", color: "var(--danger)" }}
            >
              {hb.consecutive_failures} fail
            </span>
          )}
          <button
            onClick={onFire}
            disabled={firing || !hb.task_prompt.trim()}
            className="flex items-center gap-1 rounded-[4px] px-2 py-1 font-mono text-[11px]"
            style={{
              ...actionBtn,
              opacity: firing || !hb.task_prompt.trim() ? 0.5 : 1,
              cursor: firing || !hb.task_prompt.trim() ? "not-allowed" : "pointer",
            }}
            title={hb.task_prompt.trim() ? "Fire now" : "Set a task prompt first"}
          >
            <Play className="h-3 w-3" />
            {firing ? "…" : "Fire now"}
          </button>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <div>
          <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>
            Task prompt
          </label>
          <textarea
            value={hb.task_prompt}
            onChange={(e) => onFieldChange(hb.agent_id, "task_prompt", e.target.value)}
            onBlur={(e) => onFieldSave(hb.agent_id, "task_prompt", e.target.value)}
            rows={2}
            className="w-full rounded-[5px] border px-3 py-2 text-[13px] leading-[1.5]"
            style={{ ...inputStyle, resize: "vertical" }}
            placeholder="e.g. Check my inbox and summarize important messages"
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>
              Every (min)
            </label>
            <input
              type="number"
              min={1}
              value={hb.interval_minutes}
              onChange={(e) => onFieldChange(hb.agent_id, "interval_minutes", numField(e.target.value))}
              onBlur={(e) => onFieldSave(hb.agent_id, "interval_minutes", numField(e.target.value))}
              className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>
              Max cost ($)
            </label>
            <input
              type="number"
              step={0.05}
              min={0}
              value={hb.max_cost_per_heartbeat}
              onChange={(e) => onFieldChange(hb.agent_id, "max_cost_per_heartbeat", numField(e.target.value))}
              onBlur={(e) => onFieldSave(hb.agent_id, "max_cost_per_heartbeat", numField(e.target.value))}
              className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>
              Fail threshold
            </label>
            <input
              type="number"
              min={1}
              value={hb.consecutive_failure_threshold}
              onChange={(e) => onFieldChange(hb.agent_id, "consecutive_failure_threshold", numField(e.target.value))}
              onBlur={(e) => onFieldSave(hb.agent_id, "consecutive_failure_threshold", numField(e.target.value))}
              className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]"
              style={inputStyle}
            />
          </div>
        </div>

        <div className="flex gap-6 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          <div>
            <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Last fired</span>
            <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
              {hb.last_fired ? new Date(hb.last_fired).toLocaleString() : "—"}
            </p>
          </div>
          <div>
            <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Next fire</span>
            <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
              {hb.next_fire ? new Date(hb.next_fire).toLocaleString() : "—"}
            </p>
          </div>
          {hb.last_error && (
            <div className="min-w-0 flex-1">
              <span className="font-mono text-[10px] uppercase tracking-wider" style={labelStyle}>Last error</span>
              <p className="truncate text-[12px]" style={{ color: "var(--danger)" }} title={hb.last_error}>
                {hb.last_error.substring(0, 80)}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full schedule form — once / interval / cron builder + policies
// ---------------------------------------------------------------------------

type CronPreset = "daily" | "weekdays" | "weekly" | "monthly" | "custom";

function parseCron(expr: string | null | undefined): {
  preset: CronPreset;
  time: string;
  days: number[];
  dom: number;
} {
  const fallback = { preset: "custom" as CronPreset, time: "09:00", days: [1], dom: 1 };
  if (!expr) return { ...fallback, preset: "weekdays" };
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return fallback;
  const [m, h, dom, , dow] = p;
  if (!/^\d+$/.test(m) || !/^\d+$/.test(h)) return fallback;
  const time = `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  if (dom === "*" && dow === "*") return { preset: "daily", time, days: [1], dom: 1 };
  if (dom === "*" && dow === "1-5") return { preset: "weekdays", time, days: [1, 2, 3, 4, 5], dom: 1 };
  if (dom === "*" && /^[\d,]+$/.test(dow))
    return { preset: "weekly", time, days: dow.split(",").map(Number), dom: 1 };
  if (dow === "*" && /^\d+$/.test(dom))
    return { preset: "monthly", time, days: [1], dom: Number(dom) };
  return { ...fallback, time };
}

function FullScheduleForm({
  schedule,
  agents,
  onClose,
  onSaved,
}: {
  schedule: Schedule | null;
  agents: Agent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const browserTz = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    [],
  );

  const init = schedule;
  const [agentId, setAgentId] = useState(init?.agent_id ?? agents[0]?.id ?? "");
  const [name, setName] = useState(init?.name ?? "");
  const [enabled, setEnabled] = useState(init?.enabled ?? true);
  const [kind, setKind] = useState<"once" | "interval" | "cron">(init?.trigger?.kind ?? "interval");
  const [onceAt, setOnceAt] = useState(() => {
    const at = init?.trigger?.at;
    if (!at) return "";
    const d = new Date(at);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [intervalValue, setIntervalValue] = useState(() => {
    const s = init?.trigger?.every_seconds ?? 900;
    if (s % 86400 === 0) return s / 86400;
    if (s % 3600 === 0) return s / 3600;
    return s / 60;
  });
  const [intervalUnit, setIntervalUnit] = useState<"m" | "h" | "d">(() => {
    const s = init?.trigger?.every_seconds ?? 900;
    if (s % 86400 === 0) return "d";
    if (s % 3600 === 0) return "h";
    return "m";
  });
  const cronInit = useMemo(() => parseCron(init?.trigger?.cron), [init]);
  const [cronPreset, setCronPreset] = useState<CronPreset>(cronInit.preset);
  const [cronTime, setCronTime] = useState(cronInit.time);
  const [cronDays, setCronDays] = useState<number[]>(cronInit.days);
  const [cronDom, setCronDom] = useState(cronInit.dom);
  const [cronCustom, setCronCustom] = useState(init?.trigger?.cron ?? "0 9 * * 1-5");
  const [timezone, setTimezone] = useState(init?.trigger?.timezone ?? browserTz);
  const [taskPrompt, setTaskPrompt] = useState(init?.task_prompt ?? "");
  const [missed, setMissed] = useState(init?.policies?.missed ?? "run_once");
  const [overlap, setOverlap] = useState(init?.policies?.overlap ?? "skip");
  const [failureMode, setFailureMode] = useState(init?.policies?.failure.mode ?? "no_retry");
  const [maxAttempts, setMaxAttempts] = useState(init?.policies?.failure.max_attempts ?? 3);
  const [backoff, setBackoff] = useState(init?.policies?.failure.backoff_seconds ?? 60);
  const [autoApprove, setAutoApprove] = useState<string[]>(init?.auto_approve ?? []);
  const [maxCost, setMaxCost] = useState<string>(init?.max_cost != null ? String(init.max_cost) : "");
  const [agentCaps, setAgentCaps] = useState<Agent | null>(null);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [previewTz, setPreviewTz] = useState<string>("UTC");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (agentId) api.getAgent(agentId).then(setAgentCaps).catch(() => setAgentCaps(null));
  }, [agentId]);
  const approvalCaps = (agentCaps?.capabilities ?? []).filter((c) => c.require_approval);

  const buildCronExpr = (): string => {
    const [hh, mm] = cronTime.split(":").map(Number);
    const m = Number.isFinite(mm) ? mm : 0;
    const h = Number.isFinite(hh) ? hh : 9;
    switch (cronPreset) {
      case "daily":
        return `${m} ${h} * * *`;
      case "weekdays":
        return `${m} ${h} * * 1-5`;
      case "weekly":
        return `${m} ${h} * * ${[...cronDays].sort().join(",") || "1"}`;
      case "monthly":
        return `${m} ${h} ${cronDom} * *`;
      case "custom":
        return cronCustom;
    }
  };

  const buildTrigger = (): ScheduleTrigger => {
    if (kind === "once") return { kind: "once", at: new Date(onceAt).toISOString() };
    if (kind === "interval") {
      const mult = intervalUnit === "d" ? 86400 : intervalUnit === "h" ? 3600 : 60;
      return { kind: "interval", every_seconds: intervalValue * mult };
    }
    return { kind: "cron", cron: buildCronExpr(), timezone };
  };

  const cronSummary = () =>
    `${describeCron(buildCronExpr())} · ${timezone}`;

  const handlePreview = async () => {
    setError(null);
    try {
      const r = await api.previewSchedule(buildTrigger(), 6);
      setPreview(r.occurrences);
      setPreviewTz(r.timezone);
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : "Invalid trigger");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const payload: SchedulePayload = {
      agent_id: agentId,
      name: name.trim() || "Schedule",
      enabled,
      trigger: buildTrigger(),
      task_prompt: taskPrompt,
      policies: {
        missed,
        overlap,
        failure: { mode: failureMode, max_attempts: maxAttempts, backoff_seconds: backoff },
      },
      auto_approve: autoApprove,
      max_cost: maxCost.trim() ? Number(maxCost) : null,
      // Echo API-set fields the dialog doesn't edit — PUT is full-replacement
      plan_revision_id: schedule?.plan_revision_id ?? null,
      model_override: schedule?.model_override ?? null,
      skill: schedule?.skill ?? null,
    };
    try {
      if (schedule) await api.updateSchedule(schedule.id, payload);
      else await api.createSchedule(payload);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const sel: React.CSSProperties = { ...inputStyle, border: "1px solid var(--border)" };

  return (
    <>
      <DialogTitle
        title={schedule ? "Edit schedule" : "New schedule"}
        sub={
          schedule
            ? `Creates revision ${schedule.revision_number + 1} — in-flight runs keep their captured revision`
            : "Each run is an independent session with its own captured revision"
        }
        onClose={onClose}
      />

      <div className="mt-5 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Agent</label>
            <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className="w-full rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Schedule" className="w-full rounded-[5px] border px-3 py-1.5 text-[13px]" style={inputStyle} />
          </div>
        </div>

        {/* Trigger — no cron syntax required */}
        <div>
          <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>When</label>
          <div className="flex gap-1">
            {(
              [
                ["once", "Once"],
                ["interval", "Every …"],
                ["cron", "On a schedule"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className="rounded-[4px] px-3 py-1 font-mono text-[11px] uppercase"
                style={{
                  border: "1px solid var(--border)",
                  background: kind === k ? "var(--accent)" : "var(--surface)",
                  color: kind === k ? "var(--white)" : "var(--ink-2)",
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="mt-2">
            {kind === "once" && (
              <input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]" style={inputStyle} />
            )}
            {kind === "interval" && (
              <div className="flex items-center gap-2">
                <span className="text-[13px]" style={{ color: "var(--ink-2)" }}>Every</span>
                <input type="number" min={1} value={intervalValue} onChange={(e) => setIntervalValue(Number(e.target.value))} className="w-24 rounded-[5px] border px-3 py-1.5 font-mono text-[13px]" style={inputStyle} />
                <select value={intervalUnit} onChange={(e) => setIntervalUnit(e.target.value as "m" | "h" | "d")} className="rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
                  <option value="m">minutes</option>
                  <option value="h">hours</option>
                  <option value="d">days</option>
                </select>
              </div>
            )}
            {kind === "cron" && (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <select value={cronPreset} onChange={(e) => setCronPreset(e.target.value as CronPreset)} className="rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
                    <option value="daily">Daily</option>
                    <option value="weekdays">Weekdays</option>
                    <option value="weekly">Weekly on…</option>
                    <option value="monthly">Monthly on day…</option>
                    <option value="custom">Custom expression</option>
                  </select>
                  {cronPreset !== "custom" && (
                    <input type="time" value={cronTime} onChange={(e) => setCronTime(e.target.value)} className="rounded-[5px] border px-2 py-1.5 font-mono text-[13px]" style={inputStyle} />
                  )}
                  {cronPreset === "monthly" && (
                    <input type="number" min={1} max={28} value={cronDom} onChange={(e) => setCronDom(Number(e.target.value))} className="w-16 rounded-[5px] border px-2 py-1.5 font-mono text-[13px]" style={inputStyle} title="Day of month (≤28 keeps every month safe)" />
                  )}
                </div>
                {cronPreset === "weekly" && (
                  <div className="flex gap-1">
                    {DOW.map((d, i) => {
                      const on = cronDays.includes(i);
                      return (
                        <button
                          key={d}
                          onClick={() =>
                            setCronDays((prev) => (on ? prev.filter((x) => x !== i) : [...prev, i]))
                          }
                          className="rounded-[4px] px-2 py-1 font-mono text-[11px]"
                          style={{
                            border: "1px solid var(--border)",
                            background: on ? "var(--accent)" : "var(--surface)",
                            color: on ? "var(--white)" : "var(--ink-2)",
                            cursor: "pointer",
                          }}
                        >
                          {d}
                        </button>
                      );
                    })}
                  </div>
                )}
                {cronPreset === "custom" && (
                  <input value={cronCustom} onChange={(e) => setCronCustom(e.target.value)} placeholder="0 9 * * 1-5" className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]" style={inputStyle} />
                )}
                <input list="tz-list" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Timezone (IANA)" className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]" style={inputStyle} />
                <datalist id="tz-list">
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz} />
                  ))}
                </datalist>
                <p className="font-mono text-[11px]" style={{ color: "var(--accent)" }}>
                  {cronSummary()}
                </p>
              </div>
            )}
          </div>

          <div className="mt-2">
            <button onClick={handlePreview} className="rounded-[4px] px-2.5 py-1 font-mono text-[11px]" style={{ border: "1px solid var(--border)", background: "var(--surface)", color: "var(--accent)", cursor: "pointer" }}>
              Preview next runs
            </button>
            {preview && (
              <div className="mt-2 rounded-[5px] border p-2" style={{ borderColor: "var(--border)" }}>
                <p className="font-mono text-[10px] uppercase" style={labelStyle}>
                  Next {preview.length} — shown in {previewTz}
                </p>
                {preview.length === 0 && (
                  <p className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>No upcoming fires (trigger exhausted)</p>
                )}
                {preview.map((iso, i) => (
                  <p key={i} className="font-mono text-[11px]" style={{ color: "var(--ink-2)" }}>
                    {new Date(iso).toLocaleString(undefined, { timeZone: previewTz })}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>

        <div>
          <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Task prompt</label>
          <textarea
            value={taskPrompt}
            onChange={(e) => setTaskPrompt(e.target.value)}
            rows={3}
            className="w-full rounded-[5px] border px-3 py-2 text-[13px] leading-[1.5]"
            style={{ ...inputStyle, resize: "vertical" }}
            placeholder="What should the agent do on each fire?"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>While paused/down</label>
            <select value={missed} onChange={(e) => setMissed(e.target.value as typeof missed)} className="w-full rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
              <option value="skip">skip — record + move on</option>
              <option value="run_once">run once — latest only</option>
              <option value="catch_up">catch up — every missed</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>If still running</label>
            <select value={overlap} onChange={(e) => setOverlap(e.target.value as typeof overlap)} className="w-full rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
              <option value="skip">skip this fire</option>
              <option value="queue">queue for after</option>
              <option value="cancel_previous">cancel previous</option>
              <option value="allow_parallel">run alongside</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>On failure</label>
            <select value={failureMode} onChange={(e) => setFailureMode(e.target.value as typeof failureMode)} className="w-full rounded-[5px] px-2 py-1.5 text-[13px]" style={sel}>
              <option value="no_retry">no retry</option>
              <option value="bounded_retry">bounded retry</option>
            </select>
          </div>
          {failureMode === "bounded_retry" && (
            <div className="flex gap-2">
              <div>
                <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Attempts</label>
                <input type="number" min={2} max={10} value={maxAttempts} onChange={(e) => setMaxAttempts(Number(e.target.value))} className="w-16 rounded-[5px] border px-2 py-1.5 font-mono text-[13px]" style={inputStyle} />
              </div>
              <div>
                <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Backoff s</label>
                <input type="number" min={5} value={backoff} onChange={(e) => setBackoff(Number(e.target.value))} className="w-20 rounded-[5px] border px-2 py-1.5 font-mono text-[13px]" style={inputStyle} />
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>
            Pre-approved capabilities
          </label>
          {approvalCaps.length === 0 ? (
            <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              This agent has no approval-gated capabilities — nothing to pre-approve.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {approvalCaps.map((c) => {
                const on = autoApprove.includes(c.name);
                return (
                  <button
                    key={c.name}
                    onClick={() =>
                      setAutoApprove((prev) => (on ? prev.filter((x) => x !== c.name) : [...prev, c.name]))
                    }
                    className="rounded-full px-2.5 py-1 font-mono text-[11px]"
                    style={{
                      border: "1px solid var(--border)",
                      background: on ? "var(--accent)" : "var(--surface)",
                      color: on ? "var(--white)" : "var(--ink-2)",
                      cursor: "pointer",
                    }}
                    title="Scheduled runs skip the approval prompt for this capability (still inside the agent's permission ceiling)"
                  >
                    {c.name}
                  </button>
                );
              })}
            </div>
          )}
          <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
            Pre-approval skips the prompt — it never widens the agent's capability ceiling.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider" style={labelStyle}>Max cost / run ($)</label>
            <input type="number" step={0.05} min={0} value={maxCost} onChange={(e) => setMaxCost(e.target.value)} placeholder="agent default" className="w-full rounded-[5px] border px-3 py-1.5 font-mono text-[13px]" style={inputStyle} />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-[13px]" style={{ color: "var(--ink-2)" }}>
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Enabled
            </label>
          </div>
        </div>

        {error && <ErrorBox msg={error} />}
        <DialogFooter
          onClose={onClose}
          onSave={handleSave}
          saving={saving}
          disabled={!agentId || !taskPrompt.trim()}
          label={schedule ? `Save as rev ${schedule.revision_number + 1}` : "Create schedule"}
        />
      </div>
    </>
  );
}

function DialogTitle({
  title,
  sub,
  onClose,
}: {
  title: string;
  sub?: string;
  onClose: () => void;
}) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <h2 className="text-[16px] font-semibold" style={{ color: "var(--ink)" }}>
          {title}
        </h2>
        {sub && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
            {sub}
          </p>
        )}
      </div>
      <button onClick={onClose} className="rounded-[4px] p-1" style={{ border: "none", background: "none", cursor: "pointer" }}>
        <X className="h-4 w-4" style={{ color: "var(--ink-2)" }} />
      </button>
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <p
      className="rounded-[5px] px-3 py-2 text-[12px]"
      style={{ background: "var(--surface)", color: "var(--danger)", border: "1px solid var(--danger)" }}
    >
      {msg}
    </p>
  );
}

function DialogFooter({
  onClose,
  onSave,
  saving,
  disabled,
  label,
}: {
  onClose: () => void;
  onSave: () => void;
  saving: boolean;
  disabled: boolean;
  label: string;
}) {
  return (
    <div className="flex justify-end gap-2 border-t pt-4" style={{ borderColor: "var(--border)" }}>
      <button onClick={onClose} className="rounded-[6px] px-3 py-1.5 text-[13px]" style={{ border: "1px solid var(--border)", background: "var(--surface)", color: "var(--ink-2)", cursor: "pointer" }}>
        Cancel
      </button>
      <button
        onClick={onSave}
        disabled={saving || disabled}
        className="rounded-[6px] px-4 py-1.5 text-[13px] font-medium"
        style={{
          background: "var(--accent)",
          color: "var(--white)",
          border: "none",
          cursor: saving || disabled ? "not-allowed" : "pointer",
          opacity: saving || disabled ? 0.6 : 1,
        }}
      >
        {saving ? "Saving…" : label}
      </button>
    </div>
  );
}
