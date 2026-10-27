import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Play,
  X,
  Clock,
  Plus,
  Copy,
  History,
  Pencil,
  Archive,
  Trash2,
  RotateCcw,
  HeartPulse,
} from "lucide-react";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { IconTile } from "@/components/ui/icon-tile";
import { EmptyState } from "@/components/ui/empty-state";
import { WarningBanner } from "@/components/ui/warning-banner";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { Select } from "@/components/ui/select";
import { useConfirm } from "@/lib/confirmHook";
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

const TIMEZONES: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Asia/Tokyo"];
  }
})();

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const SETUP_IDEAS = [
  { label: "Today's news", prompt: "Summarize today's top news headlines" },
  { label: "Calendar", prompt: "Tell me what's next on my calendar" },
  { label: "Daily brief", prompt: "Give me a daily brief: calendar, inbox highlights, and anything urgent" },
];

const INTERVAL_PRESETS = [
  { label: "15 min", minutes: 15 },
  { label: "30 min", minutes: 30 },
  { label: "Every hour", minutes: 60 },
  { label: "6 hours", minutes: 360 },
  { label: "Daily", minutes: 1440 },
];

/** Theoretical daily ceiling: enabled heartbeats × runs/day × per-run cap. */
function maxDailyHeartbeatSpend(hbs: HeartbeatStatus[]): number {
  return hbs
    .filter((h) => h.enabled && h.interval_minutes > 0)
    .reduce((sum, h) => sum + (1440 / h.interval_minutes) * h.max_cost_per_heartbeat, 0);
}

function shortWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

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
  const [archived, setArchived] = useState<Schedule[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [heartbeats, setHeartbeats] = useState<HeartbeatStatus[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [alerts, setAlerts] = useState<SchedulerAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [firing, setFiring] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [setupFor, setSetupFor] = useState<string | null>(null);
  const [setupBulk, setSetupBulk] = useState(false);
  const { confirm } = useConfirm();
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    // Independent fetches — one failing endpoint must not blank the page
    // (e.g. an older gateway without /api/schedules still shows heartbeats).
    const [scheds, arch, hbs, alts, agts] = await Promise.all([
      api.listSchedules().catch(() => null),
      api.listSchedules(true).catch(() => null),
      api.listHeartbeats().catch(() => null),
      api.listSchedulerAlerts().catch(() => null),
      api.listAgents().catch(() => null),
    ]);
    if (scheds) setSchedules(scheds);
    // Managed heartbeat rows belong to the Heartbeat tab even when archived —
    // an older gateway may ignore ?archived=true and hand back the full list.
    if (arch) setArchived(arch.filter((s) => !s.managed));
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
    navigate(NAV_ROUTES[page]);
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

  // Row toggle — a heartbeat can't run without a prompt, so enabling an
  // unconfigured one opens the setup panel instead of a silent no-op.
  const handleHbRowToggle = (hb: HeartbeatStatus) => {
    if (!hb.enabled && !hb.task_prompt.trim()) {
      setSetupFor(hb.agent_id);
      return;
    }
    handleHbToggle(hb);
  };

  const handleSetupSeveral = () => {
    const first = heartbeats.find((h) => !h.task_prompt.trim());
    if (first) {
      setSetupBulk(true);
      setSetupFor(first.agent_id);
    }
  };

  // After a bulk-mode save, advance to the next agent that still has no
  // prompt; otherwise close the panel.
  const handleSetupSaved = (savedId: string) => {
    fetchData();
    if (!setupBulk) {
      setSetupFor(null);
      return;
    }
    const next = heartbeats.find(
      (h) => h.agent_id !== savedId && !h.task_prompt.trim(),
    );
    setSetupFor(next ? next.agent_id : null);
    setSetupBulk(next != null);
  };

  const handleRun = async (id: string) => {
    setFiring(id);
    setRunError(null);
    try {
      const r = await api.runScheduleNow(id);
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

  const handleDelete = async (sched: Schedule) => {
    const ok = await confirm({
      title: `Archive "${sched.name}"?`,
      message:
        "The schedule stops firing and leaves the list. Its revision and occurrence history stay in the database.",
      confirmLabel: "Archive",
    });
    if (!ok) return;
    try {
      await api.deleteSchedule(sched.id);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Archive failed");
    }
  };

  const handleUnarchive = async (sched: Schedule) => {
    try {
      await api.unarchiveSchedule(sched.id);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Restore failed");
    }
  };

  const handlePurge = async (sched: Schedule) => {
    const ok = await confirm({
      title: `Delete "${sched.name}" permanently?`,
      message:
        "Removes the schedule, its revisions, and its occurrence history. This cannot be undone.",
      confirmLabel: "Delete permanently",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteSchedule(sched.id, true);
      fetchData();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Delete failed");
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
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="scheduler"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Workspace" }, { label: "Scheduler" }]}
          title="Scheduler"
          subtitle="Autonomous runs for your agents — each run is its own session with its own history."
          actions={
            <Button onClick={() => setEditing("new")}><Plus />New schedule</Button>
          }
        />

        <div className="px-8 pt-4">
          <PageIntro def={INTRO_BY_KEY.scheduler} />
        </div>

        <div className="px-8 pb-3">
          <FilterPills
            pills={[
              { key: "schedules", label: "Schedules", count: sorted.length },
              { key: "heartbeat", label: "Heartbeat", count: heartbeats.length },
            ]}
            active={mode}
            onChange={(k) => setMode(k as "schedules" | "heartbeat")}
            variant="segmented"
          />
        </div>

        {/* Run/action errors (e.g. "Schedule has no task prompt") */}
        {runError && (
          <div className="px-8 pb-3">
            <WarningBanner
              tone="danger"
              action={
                <button onClick={() => setRunError(null)} className="text-danger/70 hover:text-danger" aria-label="Dismiss">
                  <X className="h-4 w-4" />
                </button>
              }
            >
              {runError}
            </WarningBanner>
          </div>
        )}

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className="space-y-2 px-8 pb-3">
            {alerts.map((alert, i) => (
              <WarningBanner
                key={`${alert.agent_id}-${i}`}
                tone="danger"
                title={`${alert.agent_name} — failed ${alert.consecutive_failures} times (threshold: ${alert.threshold})`}
                action={
                  <button
                    onClick={() => handleClearAlert(alert.agent_id)}
                    className="text-danger/70 hover:text-danger"
                    aria-label="Clear alert"
                  >
                    <X className="h-4 w-4" />
                  </button>
                }
              >
                {alert.last_error ? alert.last_error.substring(0, 120) : "No error detail recorded."}
              </WarningBanner>
            ))}
          </div>
        )}

        {/* Schedule list — user-created schedules only */}
        {mode === "schedules" && (
        <div className="flex-1 overflow-y-auto px-8 py-4">
          {loading ? (
            <p className="py-20 text-center text-[14px] text-ink-faint">Loading…</p>
          ) : showArchived ? (
            <div className="mx-auto max-w-5xl">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[12px] text-ink-3">
                  Archived schedules — restore one (it comes back paused) or delete it for good.
                </p>
                <button
                  onClick={() => setShowArchived(false)}
                  className="text-[12px] font-medium text-accent hover:underline"
                >
                  ← Back to schedules
                </button>
              </div>
              {archived.length === 0 ? (
                <EmptyState icon={Archive} title="Nothing archived">
                  Archived schedules keep their revision and occurrence history in the database — you can restore them here later.
                </EmptyState>
              ) : (
                <div className="overflow-hidden rounded-xl border border-line bg-surface">
                  <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_110px_120px_180px] items-center gap-3 border-b border-line px-5 py-2.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Schedule</span>
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">What it does</span>
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Status</span>
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Next run</span>
                    <span />
                  </div>
                  {archived.map((sched) => (
                    <ScheduleRow
                      key={sched.id}
                      sched={sched}
                      firing={false}
                      historyOpen={false}
                      archivedView
                      onToggle={() => {}}
                      onRun={() => {}}
                      onEdit={() => {}}
                      onDuplicate={() => {}}
                      onDelete={() => {}}
                      onHistory={() => {}}
                      onRestore={() => handleUnarchive(sched)}
                      onPurge={() => handlePurge(sched)}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : sorted.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No schedules yet"
              action={<Button onClick={() => setEditing("new")}><Plus />Create your first schedule</Button>}
            >
              Attach once, interval, or cron schedules to an agent — every run is an
              independent session with its own history. For the per-agent periodic
              pulse, use the Heartbeat tab.
              {agents.length === 0 && " Create an agent first."}
              {archived.length > 0 && (
                <>
                  {" "}
                  <button onClick={() => setShowArchived(true)} className="font-medium text-accent hover:underline">
                    View {archived.length} archived
                  </button>
                </>
              )}
            </EmptyState>
          ) : (
            <div className="mx-auto max-w-5xl">
              {archived.length > 0 && (
                <div className="mb-2 flex justify-end">
                  <button
                    onClick={() => setShowArchived(true)}
                    className="text-[12px] font-medium text-ink-3 transition hover:text-ink"
                  >
                    Archived ({archived.length})
                  </button>
                </div>
              )}
              <div className="overflow-hidden rounded-xl border border-line bg-surface">
                <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_110px_120px_180px] items-center gap-3 border-b border-line px-5 py-2.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Schedule</span>
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">What it does</span>
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Status</span>
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Next run</span>
                  <span />
                </div>
                {sorted.map((sched) => (
                  <ScheduleRow
                    key={sched.id}
                    sched={sched}
                    firing={firing === sched.id}
                    historyOpen={historyFor === sched.id}
                    onToggle={() => handleToggle(sched)}
                    onRun={() => handleRun(sched.id)}
                    onEdit={() => setEditing(sched)}
                    onDuplicate={() => handleDuplicate(sched.id)}
                    onDelete={() => handleDelete(sched)}
                    onHistory={() => setHistoryFor(historyFor === sched.id ? null : sched.id)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
        )}

        {/* Heartbeat — the agent's built-in periodic pulse (per-agent config) */}
        {mode === "heartbeat" && (
          <div className="flex-1 overflow-y-auto px-8 py-4">
            {loading ? (
                <p className="py-20 text-center text-[14px] text-ink-faint">Loading…</p>
              ) : heartbeats.length === 0 ? (
                <EmptyState icon={HeartPulse} title="No agents found">
                  Create an agent first, then configure its heartbeat here.
                </EmptyState>
              ) : (
                <div className="mx-auto max-w-5xl space-y-5">
                  {/* Explainer */}
                  <div className="flex items-start gap-3 rounded-xl border border-line bg-accent-tint/60 p-4">
                    <IconTile icon={HeartPulse} tone="surface" size="md" />
                    <div>
                      <p className="text-[13px] font-semibold text-ink">What is a heartbeat?</p>
                      <p className="mt-0.5 text-[13px] leading-[1.5] text-ink-2">
                        A timer that wakes an agent to run one prompt, such as "check my
                        inbox and summarize what matters". Each agent has one. You set how
                        often it runs and how much it may spend.
                      </p>
                    </div>
                  </div>

                  {/* Summary line */}
                  <div className="flex items-baseline justify-between">
                    <p className="text-[13px] text-ink-2">
                      <span className="font-semibold text-ink">
                        {heartbeats.filter((h) => h.enabled).length} of {heartbeats.length}
                      </span>{" "}
                      heartbeats on{"  ·  "}Most you could spend today:{" "}
                      <span className="font-semibold text-ink">
                        ${maxDailyHeartbeatSpend(heartbeats).toFixed(2)}
                      </span>
                    </p>
                    {heartbeats.some((h) => !h.task_prompt.trim()) && (
                      <button
                        onClick={handleSetupSeveral}
                        className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
                      >
                        Set up several at once
                      </button>
                    )}
                  </div>

                  {/* Table */}
                  <div className="overflow-hidden rounded-xl border border-line bg-surface">
                    <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_90px_130px_120px] items-center gap-3 border-b border-line px-5 py-2.5">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Agent</span>
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">What it does</span>
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Status</span>
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Next run</span>
                      <span />
                    </div>
                    {heartbeats.map((hb) => (
                      <HeartbeatRow
                        key={hb.agent_id}
                        hb={hb}
                        selected={setupFor === hb.agent_id}
                        onToggle={() => handleHbRowToggle(hb)}
                        onSetup={() => { setSetupBulk(false); setSetupFor(hb.agent_id); }}
                      />
                    ))}
                  </div>
                </div>
              )}
          </div>
        )}
      </div>

      {setupFor && (
        <HeartbeatSetup
          key={setupFor}
          hb={heartbeats.find((h) => h.agent_id === setupFor)!}
          onClose={() => { setSetupFor(null); setSetupBulk(false); }}
          onSaved={handleSetupSaved}
          onFired={fetchData}
        />
      )}

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
// Schedule row — one schedule per line; occurrence history expands below
// ---------------------------------------------------------------------------

function ScheduleRow({
  sched,
  firing,
  historyOpen,
  archivedView,
  onToggle,
  onRun,
  onEdit,
  onDuplicate,
  onDelete,
  onHistory,
  onRestore,
  onPurge,
}: {
  sched: Schedule;
  firing: boolean;
  historyOpen: boolean;
  archivedView?: boolean;
  onToggle: () => void;
  onRun: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onHistory: () => void;
  onRestore?: () => void;
  onPurge?: () => void;
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

  const iconBtn =
    "flex h-7 w-7 items-center justify-center rounded-md border border-line bg-surface text-ink-2 transition hover:border-ink-3 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="border-t border-line first:border-t-0">
      <div className={`grid grid-cols-[minmax(0,1.6fr)_minmax(0,3fr)_110px_120px_180px] items-center gap-3 px-5 py-3 transition ${archivedView ? "opacity-75" : "hover:bg-ground"}`}>
        {/* Schedule */}
        <div className="flex min-w-0 items-center gap-3">
          {archivedView ? (
            <span className="flex h-7 w-9 shrink-0 items-center justify-center text-ink-3" title="Archived">
              <Archive className="h-4 w-4" />
            </span>
          ) : (
            <Toggle
              checked={sched.enabled}
              onCheckedChange={onToggle}
              title={sched.enabled ? "Pause" : "Resume"}
            />
          )}
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-[13px] font-semibold text-ink">{sched.name}</span>
              {managed && (
                <span className="rounded-full bg-ground px-1.5 py-0.5 font-mono text-[9px] uppercase text-ink-3">
                  heartbeat
                </span>
              )}
            </div>
            <p className="truncate text-[11px] text-ink-3">
              {sched.agent_name} · rev {sched.revision_number}
            </p>
          </div>
        </div>

        {/* What it does */}
        <div className="min-w-0">
          <p className="truncate text-[13px] text-ink-2">{triggerSummary(sched.trigger)}</p>
          <p className="truncate text-[12px] text-ink-3">
            {sched.task_prompt?.trim() || "No prompt"}
          </p>
        </div>

        {/* Status */}
        <div className="text-[13px]">
          {archivedView ? (
            <span className="text-ink-3">Archived</span>
          ) : sched.enabled ? (
            <span className="text-ink-2">On</span>
          ) : (
            <span className="text-ink-3">Off</span>
          )}
          {sched.last_status && (
            <p className="font-mono text-[11px]" style={{ color: statusColor(sched.last_status) }}>
              {sched.last_status}
            </p>
          )}
          {sched.consecutive_failures > 0 && (
            <p className="text-[11px] text-danger">{sched.consecutive_failures} failed</p>
          )}
        </div>

        {/* Next run */}
        <span className="truncate text-[12px] text-ink-3">
          {sched.next_fire_at ? shortWhen(sched.next_fire_at) : "—"}
        </span>

        {/* Actions */}
        <div className="flex items-center gap-1.5 justify-self-end">
          {archivedView ? (
            <>
              <button
                onClick={onRestore}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink transition hover:border-accent hover:text-accent"
                title="Restore — comes back paused"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Restore
              </button>
              <button
                onClick={onPurge}
                className={`${iconBtn} text-danger hover:border-danger/50 hover:text-danger`}
                title="Delete permanently — removes schedule, revisions, and history"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onRun}
                disabled={firing}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
                title="Run now"
              >
                <Play className="h-3.5 w-3.5" />
                {firing ? "…" : "Run"}
              </button>
              <button
                onClick={onHistory}
                className={`${iconBtn} ${historyOpen ? "border-accent/50 text-accent" : ""}`}
                title="Occurrence history"
              >
                <History className="h-3.5 w-3.5" />
              </button>
              <button onClick={onEdit} className={iconBtn} title={managed ? "Edit heartbeat config" : "Edit"}>
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button onClick={onDuplicate} className={iconBtn} title="Duplicate as a new disabled schedule">
                <Copy className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={onDelete}
                disabled={managed}
                className={iconBtn}
                title={managed ? "A heartbeat always exists — toggle it off instead" : "Archive"}
              >
                <Archive className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
      </div>

      {historyOpen && (
        <div className="border-t border-line bg-ground/50 px-5 py-4">
          <div className="flex gap-6">
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Last fired</span>
              <p className="text-[12px] text-ink-2">
                {sched.last_fired_at ? new Date(sched.last_fired_at).toLocaleString() : "—"}
              </p>
            </div>
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Missed / overlap</span>
              <p className="text-[12px] text-ink-2">
                {sched.policies ? `${sched.policies.missed} / ${sched.policies.overlap}` : "—"}
              </p>
            </div>
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Retry</span>
              <p className="text-[12px] text-ink-2">
                {sched.policies?.failure.mode === "bounded_retry"
                  ? `≤${sched.policies.failure.max_attempts}× (${sched.policies.failure.backoff_seconds}s)`
                  : "none"}
              </p>
            </div>
            {sched.last_error && (
              <div className="min-w-0 flex-1">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Last error</span>
                <p className="truncate text-[12px] text-danger" title={sched.last_error}>
                  {sched.last_error.substring(0, 80)}
                </p>
              </div>
            )}
          </div>
          <div className="mt-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
              Occurrence history
            </span>
            {occurrences === null ? (
              <p className="mt-1 text-[12px] text-ink-3">Loading…</p>
            ) : occurrences.length === 0 ? (
              <p className="mt-1 text-[12px] text-ink-3">No occurrences yet</p>
            ) : (
              <div className="mt-1 max-h-64 space-y-1 overflow-y-auto">
                {occurrences.map((occ) => (
                  <div
                    key={occ.id}
                    className="flex items-center gap-3 rounded-md bg-surface px-2 py-1.5 text-[12px]"
                  >
                    <span className="font-mono" style={{ color: statusColor(occ.status) }}>
                      {occ.status}
                    </span>
                    <span className="text-ink-2">
                      {new Date(occ.scheduled_for).toLocaleString()}
                    </span>
                    {occ.attempt > 1 && (
                      <span className="font-mono text-[10px] text-ink-3">
                        attempt {occ.attempt}
                      </span>
                    )}
                    {occ.run_id && (
                      <span className="font-mono text-[10px] text-ink-3">
                        run {occ.run_id.slice(0, 8)}
                      </span>
                    )}
                    {occ.error && (
                      <span className="ml-auto truncate font-mono text-[10px] text-danger" title={occ.error}>
                        {occ.error.substring(0, 60)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-6"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-[560px] overflow-y-auto rounded-xl bg-surface p-6 shadow-[0_8px_40px_rgba(0,0,0,0.25)]"
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
// Heartbeat row — one agent per line; setup happens in the side panel
// ---------------------------------------------------------------------------

function HeartbeatRow({
  hb,
  selected,
  onToggle,
  onSetup,
}: {
  hb: HeartbeatStatus;
  selected: boolean;
  onToggle: () => void;
  onSetup: () => void;
}) {
  const configured = hb.task_prompt.trim().length > 0;
  return (
    <div
      className={`grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_90px_130px_120px] items-center gap-3 px-5 py-3 transition ${
        selected ? "bg-accent-tint/50" : "hover:bg-ground"
      } border-t border-line first:border-t-0`}
    >
      <div className="flex min-w-0 items-center gap-3">
        <Toggle checked={hb.enabled} onCheckedChange={onToggle} title={hb.enabled ? "Turn off" : configured ? "Turn on" : "Set up first"} />
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-tint text-[13px] font-semibold text-accent">
          {hb.agent_name[0]?.toUpperCase() ?? "?"}
        </div>
        <span className="truncate text-[13px] font-semibold text-ink">{hb.agent_name}</span>
      </div>
      <p className={`truncate text-[13px] ${configured ? "text-ink-2" : "text-ink-3"}`}>
        {configured ? hb.task_prompt : "No prompt yet"}
      </p>
      <div className="text-[13px]">
        {hb.enabled ? (
          <span className="text-ink-2">On</span>
        ) : (
          <span className="text-ink-3">Off</span>
        )}
        {hb.consecutive_failures > 0 && (
          <p className="text-[11px] text-danger">{hb.consecutive_failures} failed</p>
        )}
      </div>
      <span className="truncate text-[12px] text-ink-3">
        {hb.enabled ? shortWhen(hb.next_fire) : "—"}
      </span>
      <button
        onClick={onSetup}
        className="flex items-center justify-center gap-1.5 justify-self-end rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink transition hover:border-accent hover:text-accent"
      >
        <Pencil className="h-3.5 w-3.5" />
        {configured ? "Edit" : "Set up"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heartbeat setup — floating modal: prompt, cadence, spend, test run
// ---------------------------------------------------------------------------

function HeartbeatSetup({
  hb,
  onClose,
  onSaved,
  onFired,
}: {
  hb: HeartbeatStatus;
  onClose: () => void;
  onSaved: (savedId: string) => void;
  onFired: () => void;
}) {
  const [prompt, setPrompt] = useState(hb.task_prompt);
  const preset = INTERVAL_PRESETS.find((p) => p.minutes === hb.interval_minutes);
  const [intervalMode, setIntervalMode] = useState<"preset" | "custom">(preset ? "preset" : "custom");
  const [intervalMin, setIntervalMin] = useState(hb.interval_minutes || 60);
  const [maxCost, setMaxCost] = useState(String(hb.max_cost_per_heartbeat ?? 0.5));
  const [failThreshold, setFailThreshold] = useState(String(hb.consecutive_failure_threshold ?? 3));
  const [enabled, setEnabled] = useState(hb.enabled);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runsPerDay = intervalMin > 0 ? Math.round(1440 / intervalMin) : 0;
  const cost = Number(maxCost) || 0;
  const dailyCap = runsPerDay * cost;
  const threshold = Number(failThreshold) || 3;

  const hasPrompt = prompt.trim().length > 0;

  const save = async (turnOn: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await api.updateHeartbeat(hb.agent_id, {
        task_prompt: prompt,
        interval_minutes: intervalMin,
        max_cost_per_heartbeat: cost,
        consecutive_failure_threshold: threshold,
        // A heartbeat without a prompt can't run — saving empty turns it off.
        enabled: hasPrompt ? (turnOn ? true : enabled) : false,
      });
      onSaved(hb.agent_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const fireOnce = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateHeartbeat(hb.agent_id, {
        task_prompt: prompt,
        interval_minutes: intervalMin,
        max_cost_per_heartbeat: cost,
        consecutive_failure_threshold: threshold,
      });
      const r = await api.fireHeartbeat(hb.agent_id);
      if (r.error) setError(r.error);
      else onFired();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[520px] flex-col overflow-hidden rounded-xl bg-surface shadow-[0_8px_40px_rgba(0,0,0,0.25)]"
        onClick={(e) => e.stopPropagation()}
      >
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-line px-5 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent-tint text-[14px] font-semibold text-accent">
          {hb.agent_name[0]?.toUpperCase() ?? "?"}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold text-ink">{hb.agent_name} heartbeat</p>
          <p className="text-[12px] text-ink-3">
            {enabled ? "On" : "Off"} · {hb.task_prompt.trim() ? "configured" : "not set up yet"}
          </p>
        </div>
        <Toggle checked={enabled} onCheckedChange={setEnabled} />
        <button onClick={onClose} className="rounded-md p-1 text-ink-3 transition hover:bg-ground hover:text-ink" aria-label="Close">
          <X className="h-4.5 w-4.5" />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        {/* Prompt */}
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">
            What should {hb.agent_name} do each time?
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            className="w-full resize-vertical rounded-lg border border-line bg-ground px-3 py-2.5 text-[13px] leading-[1.5] text-ink outline-none transition focus:border-accent"
            placeholder="e.g. Check my inbox and summarize important messages"
          />
          <p className="mt-1.5 text-[12px] text-ink-3">
            Ideas:{" "}
            {SETUP_IDEAS.map((idea, i) => (
              <span key={idea.label}>
                {i > 0 && " · "}
                <button onClick={() => setPrompt(idea.prompt)} className="text-accent hover:underline">
                  {idea.label}
                </button>
              </span>
            ))}
          </p>
        </div>

        {/* Interval */}
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">How often?</label>
          <div className="flex flex-wrap gap-2">
            {INTERVAL_PRESETS.map((p) => (
              <button
                key={p.minutes}
                onClick={() => { setIntervalMode("preset"); setIntervalMin(p.minutes); }}
                className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition ${
                  intervalMode === "preset" && intervalMin === p.minutes
                    ? "border-accent bg-accent-tint text-accent"
                    : "border-line bg-surface text-ink-2 hover:border-ink-3 hover:text-ink"
                }`}
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={() => setIntervalMode("custom")}
              className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition ${
                intervalMode === "custom"
                  ? "border-accent bg-accent-tint text-accent"
                  : "border-line bg-surface text-ink-2 hover:border-ink-3 hover:text-ink"
              }`}
            >
              Custom
            </button>
          </div>
          {intervalMode === "custom" && (
            <div className="mt-2 flex items-center gap-2">
              <input
                type="number"
                min={1}
                value={intervalMin}
                onChange={(e) => setIntervalMin(Math.max(1, Number(e.target.value) || 1))}
                className="w-24 rounded-lg border border-line bg-ground px-3 py-1.5 font-mono text-[13px] text-ink outline-none focus:border-accent"
              />
              <span className="text-[12px] text-ink-3">minutes</span>
            </div>
          )}
          <p className="mt-2 text-[12px] text-ink-3">
            Runs about {runsPerDay} time{runsPerDay === 1 ? "" : "s"} a day.
            {intervalMode === "preset" && " Custom lets you enter minutes."}
          </p>
        </div>

        {/* Spend + alert */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Spend limit per run</label>
            <input
              type="number"
              step={0.05}
              min={0}
              value={maxCost}
              onChange={(e) => setMaxCost(e.target.value)}
              className="w-full rounded-lg border border-line bg-ground px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Alert me after</label>
            <input
              type="number"
              min={1}
              value={failThreshold}
              onChange={(e) => setFailThreshold(e.target.value)}
              className="w-full rounded-lg border border-line bg-ground px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
            />
            <p className="mt-1 text-[11px] text-ink-3">failed runs in a row</p>
          </div>
        </div>

        {/* Derived daily cap */}
        <div className="rounded-lg bg-ground px-3.5 py-3">
          <p className="text-[13px] font-semibold text-ink">
            Most you could spend: ${dailyCap.toFixed(2)} a day
          </p>
          <p className="mt-0.5 text-[12px] text-ink-3">
            {runsPerDay} runs × ${cost.toFixed(2)}. Most runs should cost much less.
          </p>
        </div>

        {/* Last / next run */}
        <div className="grid grid-cols-2 gap-3 text-[13px]">
          <div>
            <p className="text-[12px] text-ink-3">Last run</p>
            <p className="mt-0.5 text-ink-2">{shortWhen(hb.last_fired)}</p>
          </div>
          <div>
            <p className="text-[12px] text-ink-3">Next run</p>
            <p className="mt-0.5 text-ink-2">
              {enabled ? shortWhen(hb.next_fire) : "After you turn it on"}
            </p>
          </div>
        </div>

        {error && <p className="text-[12px] text-danger">{error}</p>}
      </div>

      {/* Footer */}
      <div className="flex gap-2.5 border-t border-line px-5 py-4">
        <Button onClick={() => save(true)} disabled={saving} className="flex-1">
          {saving ? "Saving…" : hasPrompt ? "✓ Save and turn on" : "Save"}
        </Button>
        <Button variant="secondary" onClick={fireOnce} disabled={saving || !hasPrompt}>
          {saving ? "…" : "▷ Run once to test"}
        </Button>
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

  const fld =
    "w-full rounded-lg border border-line bg-ground px-3 py-2 text-[13px] text-ink outline-none transition focus:border-accent";
  const pill = (on: boolean) =>
    `rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition ${
      on
        ? "border-accent bg-accent-tint text-accent"
        : "border-line bg-surface text-ink-2 hover:border-ink-3 hover:text-ink"
    }`;

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

      <div className="mt-5 space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Agent</label>
            <Select
              value={agentId}
              onChange={setAgentId}
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              className={fld}
              align="left" panelClassName="text-[13px]"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Schedule" className={fld} />
          </div>
        </div>

        {/* Trigger — no cron syntax required */}
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">When</label>
          <div className="flex gap-2">
            {(
              [
                ["once", "Once"],
                ["interval", "Every …"],
                ["cron", "On a schedule"],
              ] as const
            ).map(([k, label]) => (
              <button key={k} onClick={() => setKind(k)} className={pill(kind === k)}>
                {label}
              </button>
            ))}
          </div>

          <div className="mt-3">
            {kind === "once" && (
              <input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} className={`${fld} font-mono`} />
            )}
            {kind === "interval" && (
              <div className="flex items-center gap-2">
                <span className="text-[13px] text-ink-2">Every</span>
                <input type="number" min={1} value={intervalValue} onChange={(e) => setIntervalValue(Number(e.target.value))} className={`${fld} w-24 font-mono`} />
                <Select
                  value={intervalUnit}
                  onChange={(v) => setIntervalUnit(v as "m" | "h" | "d")}
                  options={[
                    { value: "m", label: "minutes" },
                    { value: "h", label: "hours" },
                    { value: "d", label: "days" },
                  ]}
                  className={`${fld} w-auto`}
                  align="left" panelClassName="text-[13px]"
                />
              </div>
            )}
            {kind === "cron" && (
              <div className="space-y-2.5">
                <div className="flex items-center gap-2">
                  <Select
                    value={cronPreset}
                    onChange={(v) => setCronPreset(v as CronPreset)}
                    options={[
                      { value: "daily", label: "Daily" },
                      { value: "weekdays", label: "Weekdays" },
                      { value: "weekly", label: "Weekly on…" },
                      { value: "monthly", label: "Monthly on day…" },
                      { value: "custom", label: "Custom expression" },
                    ]}
                    className={`${fld} w-auto`}
                    align="left" panelClassName="text-[13px]"
                  />
                  {cronPreset !== "custom" && (
                    <input type="time" value={cronTime} onChange={(e) => setCronTime(e.target.value)} className={`${fld} w-auto font-mono`} />
                  )}
                  {cronPreset === "monthly" && (
                    <input type="number" min={1} max={28} value={cronDom} onChange={(e) => setCronDom(Number(e.target.value))} className={`${fld} w-20 font-mono`} title="Day of month (≤28 keeps every month safe)" />
                  )}
                </div>
                {cronPreset === "weekly" && (
                  <div className="flex gap-1.5">
                    {DOW.map((d, i) => {
                      const on = cronDays.includes(i);
                      return (
                        <button
                          key={d}
                          onClick={() =>
                            setCronDays((prev) => (on ? prev.filter((x) => x !== i) : [...prev, i]))
                          }
                          className={pill(on)}
                        >
                          {d}
                        </button>
                      );
                    })}
                  </div>
                )}
                {cronPreset === "custom" && (
                  <input value={cronCustom} onChange={(e) => setCronCustom(e.target.value)} placeholder="0 9 * * 1-5" className={`${fld} font-mono`} />
                )}
                <input list="tz-list" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Timezone (IANA)" className={`${fld} font-mono`} />
                <datalist id="tz-list">
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz} />
                  ))}
                </datalist>
                <p className="font-mono text-[11px] text-accent">{cronSummary()}</p>
              </div>
            )}
          </div>

          <div className="mt-3">
            <button onClick={handlePreview} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-accent transition hover:border-accent">
              Preview next runs
            </button>
            {preview && (
              <div className="mt-2 rounded-lg bg-ground p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                  Next {preview.length} — shown in {previewTz}
                </p>
                {preview.length === 0 && (
                  <p className="mt-1 text-[12px] text-ink-3">No upcoming fires (trigger exhausted)</p>
                )}
                {preview.map((iso, i) => (
                  <p key={i} className="mt-0.5 font-mono text-[11px] text-ink-2">
                    {new Date(iso).toLocaleString(undefined, { timeZone: previewTz })}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Task prompt</label>
          <textarea
            value={taskPrompt}
            onChange={(e) => setTaskPrompt(e.target.value)}
            rows={3}
            className={`${fld} resize-vertical leading-[1.5]`}
            placeholder="What should the agent do on each fire?"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">While paused/down</label>
            <Select
              value={missed}
              onChange={(v) => setMissed(v as typeof missed)}
              options={[
                { value: "skip", label: "skip — record + move on" },
                { value: "run_once", label: "run once — latest only" },
                { value: "catch_up", label: "catch up — every missed" },
              ]}
              className={fld}
              align="left" panelClassName="text-[13px]"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">If still running</label>
            <Select
              value={overlap}
              onChange={(v) => setOverlap(v as typeof overlap)}
              options={[
                { value: "skip", label: "skip this fire" },
                { value: "queue", label: "queue for after" },
                { value: "cancel_previous", label: "cancel previous" },
                { value: "allow_parallel", label: "run alongside" },
              ]}
              className={fld}
              align="left" panelClassName="text-[13px]"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">On failure</label>
            <Select
              value={failureMode}
              onChange={(v) => setFailureMode(v as typeof failureMode)}
              options={[
                { value: "no_retry", label: "no retry" },
                { value: "bounded_retry", label: "bounded retry" },
              ]}
              className={fld}
              align="left" panelClassName="text-[13px]"
            />
          </div>
          {failureMode === "bounded_retry" && (
            <div className="flex gap-3">
              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Attempts</label>
                <input type="number" min={2} max={10} value={maxAttempts} onChange={(e) => setMaxAttempts(Number(e.target.value))} className={`${fld} w-20 font-mono`} />
              </div>
              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Backoff s</label>
                <input type="number" min={5} value={backoff} onChange={(e) => setBackoff(Number(e.target.value))} className={`${fld} w-24 font-mono`} />
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">
            Pre-approved capabilities
          </label>
          {approvalCaps.length === 0 ? (
            <p className="text-[12px] text-ink-3">
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
                    className={`rounded-full border px-3 py-1 font-mono text-[11px] transition ${
                      on
                        ? "border-accent bg-accent-tint text-accent"
                        : "border-line bg-surface text-ink-2 hover:border-ink-3"
                    }`}
                    title="Scheduled runs skip the approval prompt for this capability (still inside the agent's permission ceiling)"
                  >
                    {c.name}
                  </button>
                );
              })}
            </div>
          )}
          <p className="mt-1 text-[11px] text-ink-3">
            Pre-approval skips the prompt — it never widens the agent's capability ceiling.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ink-2">Max cost / run ($)</label>
            <input type="number" step={0.05} min={0} value={maxCost} onChange={(e) => setMaxCost(e.target.value)} placeholder="agent default" className={`${fld} font-mono`} />
          </div>
          <div className="flex items-end pb-1">
            <label className="flex cursor-pointer items-center gap-2 text-[13px] text-ink-2">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="cursor-pointer accent-[var(--accent)]" />
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
        <h2 className="text-[16px] font-semibold text-ink">{title}</h2>
        {sub && <p className="mt-1 text-[11px] text-ink-3">{sub}</p>}
      </div>
      <button onClick={onClose} className="rounded-md p-1 text-ink-3 transition hover:bg-ground hover:text-ink">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <p className="rounded-lg border border-danger/50 bg-danger-tint px-3 py-2 text-[12px] text-danger">
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
    <div className="flex justify-end gap-2 border-t border-line pt-4">
      <Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button onClick={onSave} disabled={saving || disabled}>
        {saving ? "Saving…" : label}
      </Button>
    </div>
  );
}
