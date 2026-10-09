import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { Activity, DollarSign, Zap, AlertTriangle, Clock, TrendingUp, ChevronRight } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import type { DashboardStats, Agent, SpendSummary, PlatformSpendSummary, PlatformSpendRow } from "@/lib/types";

export function Observability() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.getHealth>> | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [days, setDays] = useState(7);
  const navigate = useNavigate();

  const fetchStats = useCallback(async () => {
    try {
      const data = await api.getDashboardStats(days);
      setStats(data);
    } catch {
      setStats(null);
    }
  }, [days]);

  const fetchAgents = useCallback(async () => {
    try {
      setAgents(await api.listAgents());
    } catch {}
  }, []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const fetchHealth = useCallback(async () => {
    try {
      setHealth(await api.getHealth());
    } catch {
      setHealth(null);
    }
  }, []);

  const isDesktop = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  const [setupBusy, setSetupBusy] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);

  // Runs the bundled one-time host setup; Windows shows its own consent prompt.
  const enableShellSandbox = async () => {
    setSetupBusy(true);
    setSetupError(null);
    try {
      await invoke("enable_shell_sandbox");
      await fetchHealth();
    } catch (error) {
      setSetupError(typeof error === "string" ? error : "The shell sandbox setup did not finish.");
    } finally {
      setSetupBusy(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    else if (page === "settings") navigate("/settings");
    else if (page === "vault") navigate("/vault");
    else if (page === "skills") navigate("/skills");
    else if (page === "scheduler") navigate("/scheduler");
    else if (page === "mcps") navigate("/mcps");
    else if (page === "channels") navigate("/channels");
    else if (page === "observability") navigate("/observability");
    else if (page === "traces") navigate("/traces");
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  const fmtCost = (c: number) => (c < 0.01 ? `$${c.toFixed(6)}` : `$${c.toFixed(4)}`);
  const fmtDay = (d: string) => {
    const date = new Date(d + "T00:00:00");
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  const statusColor = (s: string) => {
    if (s === "completed") return "#22c55e";
    if (s === "failed") return "#ef4444";
    if (s === "running") return "#3b82f6";
    return "var(--ink-3)";
  };

  // Chart helpers (guard against null)
  const maxRuns = stats ? Math.max(1, ...stats.time_series.map((t) => t.runs)) : 1;
  const maxCost = stats ? Math.max(0.001, ...stats.time_series.map((t) => t.cost)) : 1;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="observability"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        agentCount={agents.length}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div className="px-4 py-5 sm:px-8" style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5" style={{ color: "var(--accent)" }} />
                <h1 className="text-[18px] font-semibold text-[var(--ink)]">Overview</h1>
              </div>
              <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
                Agent observability dashboard
              </p>
            </div>
            {/* Time range selector */}
            <div className="flex gap-1">
              {[
                { d: 1, label: "Today" },
                { d: 7, label: "7 days" },
                { d: 30, label: "30 days" },
              ].map((r) => (
                <button
                  key={r.d}
                  onClick={() => setDays(r.d)}
                  className="rounded-[4px] px-3 py-1.5 text-[12px] font-medium transition"
                  style={{
                    background: days === r.d ? "var(--accent)" : "transparent",
                    color: days === r.d ? "white" : "var(--ink-2)",
                    border: "1px solid var(--border)",
                    cursor: "pointer",
                  }}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Dashboard content */}
        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto max-w-6xl space-y-6">
            <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[14px] font-semibold text-[var(--ink)]">System health</h2>
                  <p className="mt-1 text-[12px] text-[var(--ink-2)]">Live gateway and workspace readiness.</p>
                </div>
                <button type="button" onClick={() => void fetchHealth()} className="rounded border px-2.5 py-1 text-[11px] text-[var(--ink-2)] hover:bg-[var(--hover)]" style={{ borderColor: "var(--border)", cursor: "pointer" }}>Refresh</button>
              </div>
              {health ? (
                <>
                <div className="mt-4 grid grid-cols-2 gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-5">
                  <HealthMetric label="Database" value={health.database} good={health.database === "connected"} />
                  <HealthMetric label="Providers" value={String(health.providers)} good={health.providers > 0} />
                  <HealthMetric label="Agents" value={String(health.agents)} good={health.agents > 0} />
                  <HealthMetric label="Active runs" value={String(health.active_runs)} good />
                  {health.sandbox ? (
                    <HealthMetric
                      label="Shell sandbox"
                      value={
                        health.sandbox.state === "available"
                          ? health.sandbox.kind
                          : health.sandbox.state === "experimental"
                            ? `${health.sandbox.kind} (experimental)`
                            : health.sandbox.setup_required
                              ? "needs setup"
                              : "off"
                      }
                      good={health.sandbox.state !== "unavailable"}
                      neutral={health.sandbox.state === "unavailable"}
                    />
                  ) : null}
                </div>
                {health.version && health.version !== __APP_VERSION__ ? (
                  <div className="mt-3 rounded-md border px-3 py-2" style={{ borderColor: "var(--danger)" }}>
                    <p className="text-[12px] font-medium text-[var(--danger)]">
                      Version mismatch: this app is {__APP_VERSION__} but its gateway is {health.version}.
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--ink-2)]">
                      An update replaced the app but not its bundled gateway. Reinstall CaberOS from the
                      latest release before relying on this session — the two halves may disagree about
                      the database schema.
                    </p>
                  </div>
                ) : null}
                {health.sandbox && health.sandbox.state === "experimental" ? (
                  <div className="mt-3 rounded-md border px-3 py-2" style={{ borderColor: "var(--warning, #b58900)" }}>
                    <p className="text-[12px] font-medium">
                      {health.sandbox.kind} executes shell commands, but is not yet a verified security boundary.
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--ink-2)]">{health.sandbox.reason}</p>
                  </div>
                ) : null}
                {health.sandbox && health.sandbox.state === "unavailable" ? (
                  <div className="mt-3 rounded-md border px-3 py-2" style={{ borderColor: "var(--border)" }}>
                    {health.sandbox.setup_required && isDesktop ? (
                      <>
                        <p className="text-[12px] font-medium text-[var(--ink)]">
                          Shell commands are off until a one-time setup.
                        </p>
                        <p className="mt-1 text-[11px] text-[var(--ink-2)]">
                          Windows will ask for permission once. After that, agent commands run in a restricted
                          sandbox with no further prompts.
                        </p>
                        <div className="mt-2 flex items-center gap-3">
                          <button
                            type="button"
                            disabled={setupBusy}
                            onClick={() => void enableShellSandbox()}
                            className="rounded px-3 py-1.5 text-[12px] font-medium"
                            style={{
                              background: "var(--accent)",
                              color: "white",
                              cursor: setupBusy ? "default" : "pointer",
                              opacity: setupBusy ? 0.6 : 1,
                            }}
                          >
                            {setupBusy ? "Waiting for Windows…" : "Enable shell sandbox"}
                          </button>
                          {setupError ? (
                            <span className="text-[11px] text-[var(--danger)]">{setupError}</span>
                          ) : null}
                        </div>
                      </>
                    ) : (
                      <p className="text-[12px] text-[var(--ink-2)]">
                        Agents cannot run shell commands on this machine. {health.sandbox.reason}
                      </p>
                    )}
                    <p className="mt-2 text-[11px] text-[var(--ink-3)]">
                      Every other capability — files, web, memory, skills, knowledge and MCP tools — is unaffected.
                    </p>
                  </div>
                ) : null}
                </>
              ) : (
                <div className="mt-4 flex items-center justify-between gap-3 rounded-md border px-3 py-2" style={{ borderColor: "var(--danger)" }}>
                  <p className="text-[12px] text-[var(--danger)]">Health data is unavailable. Check the gateway and retry.</p>
                  <button type="button" onClick={() => void fetchHealth()} className="shrink-0 rounded border px-2.5 py-1 text-[11px] text-[var(--ink-2)]" style={{ borderColor: "var(--border)", cursor: "pointer" }}>Retry</button>
                </div>
              )}
            </div>
            {stats ? (
              <>
                {/* KPI cards */}
                <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                  <KpiCard
                    icon={Activity}
                    label="Total runs"
                    value={stats.total_runs.toString()}
                    sub={`${days === 1 ? "today" : `${days} days`}`}
                  />
                  <KpiCard
                    icon={DollarSign}
                    label="Total cost"
                    value={fmtCost(stats.total_cost)}
                    sub={`${days === 1 ? "today" : `${days} days`}`}
                  />
                  <KpiCard
                    icon={Zap}
                    label="Total tokens"
                    value={stats.total_tokens.toLocaleString()}
                    sub="in + out"
                  />
                  <KpiCard
                    icon={AlertTriangle}
                    label="Error rate"
                    value={`${stats.error_rate}%`}
                    sub={`${stats.error_count} failed`}
                    color={stats.error_rate > 10 ? "#ef4444" : undefined}
                  />
                  <KpiCard
                    icon={Clock}
                    label="Avg latency"
                    value={stats.avg_latency_ms > 1000
                      ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s`
                      : `${stats.avg_latency_ms}ms`}
                    sub="per run"
                  />
                </div>

                {/* Charts row */}
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {/* Runs per day */}
                  <ChartCard title="Runs per day">
                    <BarChart
                      data={stats.time_series.map((t) => ({ label: fmtDay(t.date), value: t.runs, maxValue: maxRuns }))}
                      color="#3b82f6"
                      valueFormatter={(v) => `${v} runs`}
                    />
                  </ChartCard>

                  {/* Cost per day */}
                  <ChartCard title="Cost per day">
                    <BarChart
                      data={stats.time_series.map((t) => ({ label: fmtDay(t.date), value: t.cost, maxValue: maxCost }))}
                      color="#22c55e"
                      valueFormatter={(v) => fmtCost(v)}
                    />
                  </ChartCard>
                </div>

                {/* Bottom row: agents + recent runs */}
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {/* Top agents */}
                  <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
                    <div className="mb-3 flex items-center gap-2">
                      <TrendingUp className="h-4 w-4" style={{ color: "var(--accent)" }} />
                      <h3 className="text-[14px] font-semibold text-[var(--ink)]">Top agents by cost</h3>
                    </div>
                    {stats.by_agent.length === 0 ? (
                      <p className="text-[12px] text-[var(--ink-3)]">No agent activity</p>
                    ) : (
                      <div className="space-y-3">
                        {stats.by_agent.slice(0, 5).map((a) => {
                          const pct = stats.total_cost > 0 ? (a.total_cost / stats.total_cost) * 100 : 0;
                          return (
                            <div
                              key={a.agent_id}
                              className="cursor-pointer rounded-[4px] p-2 transition hover:bg-[var(--surface)]"
                              onClick={() => navigate(`/traces/${a.agent_id}`)}
                            >
                              <div className="flex items-center justify-between text-[12px]">
                                <span className="font-medium text-[var(--ink)]">
                                  {a.agent_name || agentName(a.agent_id)}
                                </span>
                                <span className="text-[var(--ink-2)]">
                                  {fmtCost(a.total_cost)} · {a.run_count} runs
                                </span>
                              </div>
                              <div className="mt-1 flex items-center gap-2">
                                <div className="h-1.5 flex-1 rounded-full" style={{ background: "var(--border)" }}>
                                  <div
                                    className="h-1.5 rounded-full transition-all"
                                    style={{ width: `${pct}%`, background: "var(--accent)" }}
                                  />
                                </div>
                                <span className="text-[10px] text-[var(--ink-3)]">
                                  {a.error_count > 0 ? `${a.error_count} errors` : "no errors"}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Recent runs */}
                  <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-[14px] font-semibold text-[var(--ink)]">Recent runs</h3>
                      <button
                        onClick={() => navigate("/traces")}
                        className="text-[12px] text-[var(--accent)]"
                        style={{ background: "none", border: "none", cursor: "pointer" }}
                      >
                        View all →
                      </button>
                    </div>
                    {stats.recent_runs.length === 0 ? (
                      <p className="text-[12px] text-[var(--ink-3)]">No recent runs</p>
                    ) : (
                      <div className="space-y-1">
                        {stats.recent_runs.slice(0, 6).map((r) => (
                          <div
                            key={r.id}
                            className="flex cursor-pointer items-center gap-2 rounded-[4px] p-2 text-[12px] transition hover:bg-[var(--surface)]"
                            onClick={() => navigate(`/traces/${r.agent_id}/${r.id}`)}
                          >
                            <div className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor(r.status) }} />
                            <span className="flex-1 truncate text-[var(--ink)]">
                              {r.agent_name || agentName(r.agent_id)}
                            </span>
                            <span className="text-[var(--ink-3)]">{fmtCost(r.cost)}</span>
                            <span className="text-[var(--ink-3)]">{r.tokens_in + r.tokens_out} tok</span>
                            <ChevronRight className="h-3 w-3 text-[var(--ink-3)]" />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Spend — agent totals vs the model-call ledger */}
                <SpendSection days={days} agents={agents} />
              </>
            ) : (
              <div className="py-20 text-center">
                <p className="text-[14px] text-[var(--ink-3)]">Loading dashboard...</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Reusable components ---

function HealthMetric({
  label,
  value,
  good,
  neutral = false,
}: {
  label: string;
  value: string;
  good: boolean;
  /** A supported state that is not a failure (e.g. an optional feature that is off). */
  neutral?: boolean;
}) {
  const color = neutral ? "var(--ink-2)" : good ? "var(--accent)" : "var(--danger)";
  return (
    <div className="rounded-md border px-3 py-2" style={{ borderColor: "var(--border)" }}>
      <p className="text-[10px] uppercase tracking-wide text-[var(--ink-3)]">{label}</p>
      <p className="mt-1 font-medium" style={{ color }}>{value}</p>
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  sub: string;
  color?: string;
}) {
  return (
    <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5" style={{ color: color || "var(--ink-3)" }} />
        <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">{label}</p>
      </div>
      <p className="mt-2 text-[22px] font-semibold" style={{ color: color || "var(--ink)" }}>
        {value}
      </p>
      <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">{sub}</p>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
      <h3 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">{title}</h3>
      {children}
    </div>
  );
}

function BarChart({
  data,
  color,
  valueFormatter,
}: {
  data: { label: string; value: number; maxValue: number }[];
  color: string;
  valueFormatter: (v: number) => string;
}) {
  return (
    <div className="flex h-32 items-end gap-1">
      {data.map((d, i) => {
        const heightPct = d.maxValue > 0 ? (d.value / d.maxValue) * 100 : 0;
        return (
          <div key={i} className="group relative flex flex-1 flex-col items-center justify-end" style={{ height: "100%" }}>
            {/* Tooltip */}
            <div
              className="pointer-events-none absolute -top-8 z-10 whitespace-nowrap rounded-[3px] px-2 py-1 text-[10px] opacity-0 transition group-hover:opacity-100"
              style={{ background: "var(--ink)", color: "var(--white)" }}
            >
              {d.label}: {valueFormatter(d.value)}
            </div>
            {/* Bar */}
            <div
              className="w-full rounded-t-[2px] transition-all"
              style={{
                height: `${Math.max(heightPct, 2)}%`,
                background: d.value > 0 ? color : "var(--border)",
                minHeight: 2,
              }}
            />
            {/* Label (every Nth bar to avoid crowding) */}
            {data.length <= 7 || i % Math.ceil(data.length / 7) === 0 ? (
              <span className="mt-1 text-[9px] text-[var(--ink-3)]">{d.label}</span>
            ) : (
              <span className="mt-1 text-[9px] opacity-0">.</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- Spend section: agent run-totals vs platform ledger ---

type SpendView =
  | { key: string; scope: "agent"; data: SpendSummary }
  | { key: string; scope: "platform"; data: PlatformSpendSummary };

interface SpendDraft {
  agent_id: string;
  provider_id: string;
  model: string;
  purpose: string;
  kind: string;
}

const KIND_LABELS: Record<string, string> = {
  chat: "Chat",
  embedding: "Embedding",
  probe: "Probe",
  extract: "Extract",
  title: "Title",
};
const KIND_OPTIONS = ["chat", "embedding", "probe", "extract", "title"];
const PURPOSE_OPTIONS = ["reasoning", "embedding", "probe", "extract", "title"];

/** Human provider name; short id suffix when two providers share a name
 * or the row is gone (deleted/unknown). UUIDs never lead. */
function providerLabel(id: string | null | undefined, names: Record<string, string>): string {
  if (!id) return "—";
  const name = names[id];
  if (!name) return `Unknown provider · ${id.slice(0, 8)}`;
  const dupes = Object.values(names).filter((n) => n === name).length;
  return dupes > 1 ? `${name} · ${id.slice(0, 8)}` : name;
}

export function SpendSection({ days, agents }: { days: number; agents: Agent[] }) {
  const [scope, setScope] = useState<"agent" | "platform">("agent");
  const [view, setView] = useState<SpendView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providerNames, setProviderNames] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<SpendDraft>({
    agent_id: "",
    provider_id: "",
    model: "",
    purpose: "",
    kind: "",
  });
  const [applied, setApplied] = useState<SpendDraft>(filters);
  const seq = useRef(0);
  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  const fmtCost = (c: number) => (c < 0.01 ? `$${c.toFixed(6)}` : `$${c.toFixed(4)}`);

  // Provider names for labels + the filter dropdown — best-effort, the
  // spend data renders regardless.
  useEffect(() => {
    api
      .listProviders()
      .then((ps) => setProviderNames(Object.fromEntries(ps.map((x) => [x.id, x.name]))))
      .catch(() => {});
  }, []);

  // The rendered payload must match the ACTIVE request key — a stale
  // platform payload is never shown under new filter labels.
  const requestKey = `${scope}:${days}:${JSON.stringify(applied)}`;
  const visible = view && view.key === requestKey ? view : null;

  useEffect(() => {
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    setView(null); // clear stale data immediately — no wrong-filter render
    const job =
      scope === "agent"
        ? api.getSpend(days, applied.agent_id || undefined).then((d) => {
            if (my === seq.current)
              setView({ key: requestKey, scope: "agent", data: d });
          })
        : api
            .getPlatformSpend({
              days,
              agent_id: applied.agent_id || undefined,
              provider_id: applied.provider_id || undefined,
              model: applied.model || undefined,
              purpose: applied.purpose || undefined,
              kind: applied.kind || undefined,
            })
            .then((d) => {
              if (my === seq.current)
                setView({ key: requestKey, scope: "platform", data: d });
            });
    job
      .catch(() => {
        if (my === seq.current) setError("Couldn't load spend data.");
      })
      .finally(() => {
        if (my === seq.current) setLoading(false);
      });
  }, [scope, days, applied, requestKey]);

  const select = (
    key: keyof SpendDraft,
    label: string,
    options: { value: string; label: string }[],
    allLabel: string,
  ) => (
    <label className="flex flex-col gap-0.5" key={key}>
      <span className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">{label}</span>
      <select
        value={filters[key]}
        onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
        className="w-36 max-w-full rounded-[4px] px-2 py-1 text-[11px] text-[var(--ink)]"
        style={{ border: "1px solid var(--border)", background: "var(--white)" }}
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="mt-4 rounded-xl p-4" style={{ border: "1px solid var(--border-soft)", background: "var(--sidebar)" }}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <DollarSign className="h-4 w-4" style={{ color: "var(--accent)" }} />
          <h3 className="text-[14px] font-semibold text-[var(--ink)]">Spend</h3>
          <div className="ml-2 flex gap-1" role="group" aria-label="Spend scope">
            {(["agent", "platform"] as const).map((sc) => (
              <button
                key={sc}
                aria-pressed={scope === sc}
                onClick={() => setScope(sc)}
                className="rounded-[4px] px-2.5 py-1 text-[11px] font-medium"
                style={{
                  background: scope === sc ? "var(--accent)" : "var(--white)",
                  color: scope === sc ? "var(--accent-text, white)" : "var(--ink-2)",
                  border: "1px solid var(--border)",
                  cursor: "pointer",
                }}
              >
                {sc === "agent" ? "Agent" : "Platform"}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label htmlFor="spend-agent" className="flex flex-col gap-0.5">
            <span className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">Agent</span>
            <select
              id="spend-agent"
              value={filters.agent_id}
              onChange={(e) => setFilters({ ...filters, agent_id: e.target.value })}
              className="max-w-full rounded-[4px] px-2 py-1 text-[11px] text-[var(--ink)]"
              style={{ border: "1px solid var(--border)", background: "var(--white)" }}
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          {scope === "platform" && (
            <>
              {select(
                "provider_id",
                "Provider",
                Object.entries(providerNames).map(([id, name]) => ({ value: id, label: name })),
                "All providers",
              )}
              <label className="flex flex-col gap-0.5">
                <span className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">Model</span>
                <input
                  value={filters.model}
                  onChange={(e) => setFilters({ ...filters, model: e.target.value })}
                  className="w-36 max-w-full rounded-[4px] px-2 py-1 text-[11px] text-[var(--ink)]"
                  style={{ border: "1px solid var(--border)", background: "var(--white)" }}
                />
              </label>
              {select(
                "purpose",
                "Purpose",
                PURPOSE_OPTIONS.map((v) => ({ value: v, label: v })),
                "All purposes",
              )}
              {select(
                "kind",
                "Kind",
                KIND_OPTIONS.map((v) => ({ value: v, label: KIND_LABELS[v] ?? v })),
                "All kinds",
              )}
            </>
          )}
          <button
            onClick={() => setApplied({ ...filters })}
            className="rounded-[4px] px-2.5 py-1.5 text-[11px] font-medium"
            style={{ background: "var(--accent)", color: "var(--accent-text, white)", border: "none", cursor: "pointer" }}
          >
            Apply
          </button>
        </div>
      </div>

      {loading && <p className="text-[12px] text-[var(--ink-3)]">Loading spend…</p>}
      {error && !loading && (
        <p className="text-[12px]" style={{ color: "#ef4444" }}>{error}</p>
      )}
      {!loading && !error && !visible && (
        <p className="text-[12px] text-[var(--ink-3)]">No spend data for this selection.</p>
      )}

      {!loading && !error && visible?.scope === "agent" && (
        <div>
          <div className="grid grid-cols-2 gap-3 text-[12px] md:grid-cols-4">
            <Metric label="Total" value={fmtCost(visible.data.total_cost)} />
            <Metric label="Runs" value={String(visible.data.total_runs)} />
            <Metric label="Tokens in" value={visible.data.total_tokens_in.toLocaleString()} />
            <Metric label="Tokens out" value={visible.data.total_tokens_out.toLocaleString()} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="overflow-x-auto">
              <p className="mb-1 text-[10px] uppercase text-[var(--ink-3)]">By agent</p>
              <table className="w-full text-[11px]">
                <tbody>
                  {visible.data.by_agent.map((r) => (
                    <tr key={r.agent_id} className="border-t" style={{ borderColor: "var(--border)" }}>
                      <td className="py-1">{r.agent_name || agentName(r.agent_id)}</td>
                      <td className="py-1 text-right tabular-nums">{r.run_count} runs</td>
                      <td className="py-1 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
                      <td className="py-1 text-right tabular-nums text-[var(--ink-3)]">{(r.tokens_in + r.tokens_out).toLocaleString()}</td>
                    </tr>
                  ))}
                  {visible.data.by_agent.length === 0 && (
                    <tr><td className="py-1 text-[var(--ink-3)]">none</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto">
              <p className="mb-1 text-[10px] uppercase text-[var(--ink-3)]">By trigger</p>
              <table className="w-full text-[11px]">
                <tbody>
                  {Object.entries(visible.data.by_trigger).map(([trigger, cost]) => (
                    <tr key={trigger} className="border-t" style={{ borderColor: "var(--border)" }}>
                      <td className="py-1">{trigger}</td>
                      <td className="py-1 text-right tabular-nums">{fmtCost(cost)}</td>
                    </tr>
                  ))}
                  {Object.keys(visible.data.by_trigger).length === 0 && (
                    <tr><td className="py-1 text-[var(--ink-3)]">none</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <p className="mt-2 text-[10px] text-[var(--ink-3)]">
            Run totals — the historic accounting shape; not reconcilable to
            ledger platform totals.
          </p>
        </div>
      )}

      {!loading && !error && visible?.scope === "platform" && (
        <PlatformSpendView
          data={visible.data}
          providerNames={providerNames}
          fmtCost={fmtCost}
        />
      )}

      {scope === "platform" && (
        <p className="mt-2 text-[10px] text-[var(--ink-3)]">
          Ledger calls only — pre-ledger runs aren't reconstructed, test
          runs are excluded, and runless/deleted-run calls are included.
          Agent totals and platform totals count different things.
        </p>
      )}
    </div>
  );
}

function PricingCoverage({ row }: { row: PlatformSpendRow }) {
  if (row.priced_calls === undefined) {
    return <span className="text-[var(--ink-3)]">—</span>;
  }
  const unpriced = row.unpriced_calls ?? row.call_count - row.priced_calls;
  if (unpriced === 0) return <span className="text-[var(--success,#22c55e)]">priced</span>;
  if (row.priced_calls === 0) return <span style={{ color: "var(--warning,#b08968)" }}>unpriced</span>;
  return <span style={{ color: "var(--warning,#b08968)" }}>partial</span>;
}

function PlatformSpendView({
  data,
  providerNames,
  fmtCost,
}: {
  data: PlatformSpendSummary;
  providerNames: Record<string, string>;
  fmtCost: (c: number) => string;
}) {
  const hasCoverage = data.priced_calls !== undefined;
  const calls = data.total_calls;
  const allUnpriced = hasCoverage && calls > 0 && data.priced_calls === 0;
  const unpricedExact = data.unpriced_calls ?? (hasCoverage ? calls - (data.priced_calls ?? 0) : 0);

  const mainSpend =
    calls === 0
      ? "$0"
      : !hasCoverage
        ? fmtCost(data.total_cost)
        : allUnpriced
          ? "Unknown"
          : fmtCost(data.total_cost);

  return (
    <div>
      {/* Pricing-truth warning — the headline number must not claim a
          precise total the ledger can't back. */}
      {hasCoverage && calls > 0 && unpricedExact > 0 && (
        <p className="mb-2 text-[11px] font-medium" style={{ color: "var(--warning, #b08968)" }}>
          {allUnpriced
            ? `Actual spend is unknown: ${unpricedExact} of ${calls} calls lack pricing data.`
            : `Recorded amount is incomplete: pricing unavailable for ${unpricedExact} of ${calls} calls.`}
        </p>
      )}
      {!hasCoverage && calls > 0 && (
        <p className="mb-2 text-[11px] text-[var(--ink-3)]">Pricing coverage unavailable.</p>
      )}

      <div className="grid grid-cols-2 gap-3 text-[12px] md:grid-cols-4">
        <div>
          <p className="text-[9px] uppercase text-[var(--ink-3)]">
            {allUnpriced ? "Spend" : "Recorded cost"}
          </p>
          <p className="font-semibold text-[var(--ink)]">
            {allUnpriced ? "Unknown" : mainSpend}
          </p>
          {allUnpriced && (
            <p className="text-[10px] text-[var(--ink-3)]">{fmtCost(data.total_cost)} recorded</p>
          )}
        </div>
        <Metric label="Calls" value={String(calls)} />
        <Metric label="Runs" value={String(data.total_runs)} />
        <Metric label="In / out tokens" value={`${data.total_tokens_in.toLocaleString()} / ${data.total_tokens_out.toLocaleString()}`} />
        {hasCoverage && (
          <Metric
            label="Priced calls"
            value={`${data.priced_calls} / ${calls}`}
          />
        )}
        <Metric
          label="Thinking tokens"
          value={
            data.thinking_tokens == null
              ? "Not reported"
              : data.thinking_tokens.toLocaleString()
          }
        />
        {data.thinking_reported_calls !== undefined && calls > 0 && (
          <Metric label="Thinking reported" value={`${data.thinking_reported_calls} of ${calls} calls`} />
        )}
        <Metric
          label="Cached tokens"
          value={data.cached_tokens == null ? "Not reported" : data.cached_tokens.toLocaleString()}
        />
      </div>

      {/* By model — full width, one row per provider+model pair */}
      <div className="mt-3 overflow-x-auto">
        <p className="mb-1 text-[10px] uppercase text-[var(--ink-3)]">By model</p>
        <table className="w-full min-w-[600px] text-[11px]">
          <thead>
            <tr className="text-left text-[9px] uppercase text-[var(--ink-3)]">
              <th className="pb-0.5 w-[26%]">Model</th>
              <th className="pb-0.5 w-[24%]">Provider</th>
              <th className="whitespace-nowrap px-2 pb-0.5 text-right">Calls</th>
              <th className="whitespace-nowrap px-2 pb-0.5 text-right">Recorded cost</th>
              <th className="whitespace-nowrap px-2 pb-0.5 text-right">Pricing</th>
              <th className="whitespace-nowrap px-2 pb-0.5 text-right">Thinking</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model.map((r, i) => (
              <tr key={`${r.provider_id}/${r.model_name}/${i}`} className="border-t" style={{ borderColor: "var(--border)" }}>
                <td className="max-w-0 truncate px-2 py-1 font-medium text-[var(--ink)]" title={r.model_name ?? undefined}>
                  {r.model_name ?? "unknown model"}
                </td>
                <td className="max-w-0 truncate px-2 py-1 text-[var(--ink-2)]" title={r.provider_id ?? undefined}>
                  {providerLabel(r.provider_id, providerNames)}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums">{r.call_count}</td>
                <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
                <td className="whitespace-nowrap px-2 py-1 text-right"><PricingCoverage row={r} /></td>
                <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums text-[var(--ink-3)]">
                  {r.thinking_tokens == null ? "Not reported" : r.thinking_tokens.toLocaleString()}
                </td>
              </tr>
            ))}
            {data.by_model.length === 0 && (
              <tr><td className="py-1 text-[var(--ink-3)]" colSpan={6}>none</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* By provider / by kind — side by side only when wide enough */}
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <SpendBreakdown
          title="By provider"
          rows={data.by_provider}
          label={(r) => providerLabel(r.provider_id, providerNames)}
          titleAttr={(r) => r.provider_id ?? undefined}
          fmtCost={fmtCost}
        />
        <SpendBreakdown
          title="By kind"
          rows={data.by_kind}
          label={(r) => KIND_LABELS[r.kind ?? ""] ?? (r.kind ?? "—")}
          fmtCost={fmtCost}
        />
      </div>
    </div>
  );
}

function SpendBreakdown({
  title,
  rows,
  label,
  titleAttr,
  fmtCost,
}: {
  title: string;
  rows: PlatformSpendRow[];
  label: (r: PlatformSpendRow) => string;
  titleAttr?: (r: PlatformSpendRow) => string | undefined;
  fmtCost: (c: number) => string;
}) {
  return (
    <div className="overflow-x-auto">
      <p className="mb-1 text-[10px] uppercase text-[var(--ink-3)]">{title}</p>
      <table className="w-full min-w-[480px] text-[11px]">
        <thead>
          <tr className="text-left text-[9px] uppercase text-[var(--ink-3)]">
            <th className="pb-0.5 w-[40%]">Name</th>
            <th className="whitespace-nowrap px-2 pb-0.5 text-right">Calls</th>
            <th className="whitespace-nowrap px-2 pb-0.5 text-right">Recorded cost</th>
            <th className="whitespace-nowrap px-2 pb-0.5 text-right">Pricing</th>
            <th className="whitespace-nowrap px-2 pb-0.5 text-right">Thinking</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t" style={{ borderColor: "var(--border)" }}>
              <td className="max-w-0 truncate px-2 py-1" title={titleAttr?.(r) ?? label(r)}>{label(r)}</td>
              <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums">{r.call_count}</td>
              <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
              <td className="whitespace-nowrap px-2 py-1 text-right"><PricingCoverage row={r} /></td>
              <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums text-[var(--ink-3)]">
                {r.thinking_tokens == null ? "Not reported" : r.thinking_tokens.toLocaleString()}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td className="py-1 text-[var(--ink-3)]" colSpan={5}>none</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] uppercase text-[var(--ink-3)]">{label}</p>
      <p className="font-semibold text-[var(--ink)]">{value}</p>
    </div>
  );
}
