import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, DollarSign, Zap, AlertTriangle, Clock, TrendingUp, ChevronRight } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import type { DashboardStats, Agent } from "@/lib/types";

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
        <div className="px-8 py-5" style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}>
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
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-6xl space-y-6">
            <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[14px] font-semibold text-[var(--ink)]">System health</h2>
                  <p className="mt-1 text-[12px] text-[var(--ink-2)]">Live gateway and workspace readiness.</p>
                </div>
                <button type="button" onClick={() => void fetchHealth()} className="rounded border px-2.5 py-1 text-[11px] text-[var(--ink-2)] hover:bg-[var(--hover)]" style={{ borderColor: "var(--border)", cursor: "pointer" }}>Refresh</button>
              </div>
              {health ? (
                <div className="mt-4 grid grid-cols-4 gap-3 text-[12px]">
                  <HealthMetric label="Database" value={health.database} good={health.database === "connected"} />
                  <HealthMetric label="Providers" value={String(health.providers)} good={health.providers > 0} />
                  <HealthMetric label="Agents" value={String(health.agents)} good={health.agents > 0} />
                  <HealthMetric label="Active runs" value={String(health.active_runs)} good />
                </div>
              ) : <p className="mt-4 text-[12px] text-[var(--danger)]">Health data is unavailable. Check the gateway and retry.</p>}
            </div>
            {stats ? (
              <>
                {/* KPI cards */}
                <div className="grid grid-cols-5 gap-4">
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
                <div className="grid grid-cols-2 gap-4">
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
                <div className="grid grid-cols-2 gap-4">
                  {/* Top agents */}
                  <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
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
                  <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
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

function HealthMetric({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="rounded-md border px-3 py-2" style={{ borderColor: "var(--border)" }}>
      <p className="text-[10px] uppercase tracking-wide text-[var(--ink-3)]">{label}</p>
      <p className="mt-1 font-medium" style={{ color: good ? "var(--accent)" : "var(--danger)" }}>{value}</p>
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
    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
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
    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
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
