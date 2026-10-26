import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { ChevronDown, Download, RefreshCw, TrendingUp } from "lucide-react";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { StatCard } from "@/components/ui/stat-card";
import { SectionCard } from "@/components/ui/section-card";
import { WarningBanner } from "@/components/ui/warning-banner";
import { StatusWord, type StatusKind } from "@/components/ui/status-word";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import type { DashboardStats, Agent, SpendSummary, PlatformSpendSummary, PlatformSpendRow } from "@/lib/types";

const RUN_STATUS: Record<string, { kind: StatusKind; label: string }> = {
  completed: { kind: "success", label: "Succeeded" },
  failed: { kind: "failed", label: "Failed" },
  running: { kind: "running", label: "Running" },
  awaiting_approval: { kind: "paused", label: "Awaiting approval" },
  stopped: { kind: "idle", label: "Stopped" },
  interrupted: { kind: "idle", label: "Interrupted" },
};

export function Observability() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.getHealth>> | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [days, setDays] = useState(7);
  const navigate = useNavigate();

  const fetchStats = useCallback(async () => {
    try {
      setStats(await api.getDashboardStats(days));
      setStatsFailed(false);
    } catch {
      setStats(null);
      setStatsFailed(true);
    }
  }, [days]);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  const fetchHealth = useCallback(async () => {
    try {
      setHealth(await api.getHealth());
      setHealthFailed(false);
    } catch {
      setHealth(null);
      setHealthFailed(true);
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
    void fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const refresh = () => {
    void fetchStats();
    void fetchHealth();
  };

  const [exportOpen, setExportOpen] = useState(false);

  const download = (name: string, blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Exports of the visible window — honest data, no formatting tricks.
  const exportCsv = () => {
    if (!stats) return;
    const rows = [
      "date,runs,errors,tokens,cost_usd",
      ...stats.time_series.map(
        (t) => `${t.date},${t.runs},${t.errors},${t.tokens},${t.cost}`,
      ),
      "",
      "agent,runs,errors,tokens,cost_usd",
      ...stats.by_agent.map(
        (a) =>
          `"${(a.agent_name ?? a.agent_id).replace(/"/g, '""')}",${a.run_count},${a.error_count},${a.total_tokens},${a.total_cost}`,
      ),
    ];
    download(`caberos-overview-${days}d.csv`, new Blob([rows.join("\n")], { type: "text/csv" }));
  };

  const exportJson = () => {
    if (!stats) return;
    download(
      `caberos-overview-${days}d.json`,
      new Blob([JSON.stringify(stats, null, 2)], { type: "application/json" }),
    );
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  const fmtCost = (c: number) => (c < 0.01 ? `$${c.toFixed(6)}` : `$${c.toFixed(4)}`);
  const fmtDay = (d: string) => {
    const date = new Date(d + "T00:00:00");
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };
  const windowLabel = days === 1 ? "today" : `${days} days`;

  const maxRuns = stats ? Math.max(1, ...stats.time_series.map((t) => t.runs)) : 1;
  const maxCost = stats ? Math.max(1, ...stats.time_series.map((t) => t.cost)) : 1;
  const anyCost = stats?.time_series.some((t) => t.cost > 0) ?? false;
  const failingAgents = stats?.by_agent.filter((a) => a.error_count > 0) ?? [];

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="observability"
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Observability" }, { label: "Overview" }]}
          title="Overview"
          subtitle="How your agents have been doing."
          actions={
            <>
              <div className="relative">
                <Button variant="outline" size="sm" onClick={() => setExportOpen((v) => !v)} disabled={!stats}>
                  <Download className="h-3.5 w-3.5" />
                  Export
                  <ChevronDown className="h-3 w-3" />
                </Button>
                {exportOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setExportOpen(false)} />
                    <div className="absolute right-0 top-9 z-20 w-44 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-lg">
                      <button
                        type="button"
                        onClick={() => { setExportOpen(false); exportCsv(); }}
                        className="w-full cursor-pointer px-3 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                      >
                        CSV (.csv)
                      </button>
                      <button
                        type="button"
                        onClick={() => { setExportOpen(false); exportJson(); }}
                        className="w-full cursor-pointer px-3 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                      >
                        JSON (.json)
                      </button>
                      <button
                        type="button"
                        onClick={() => { setExportOpen(false); void api.exportStatsXlsx(days); }}
                        className="w-full cursor-pointer px-3 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                      >
                        Excel (.xlsx)
                      </button>
                    </div>
                  </>
                )}
              </div>
              <Button variant="outline" size="sm" onClick={refresh}>
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </Button>
            </>
          }
        />

        <div className="px-8 pb-4">
          <FilterPills
            variant="segmented"
            pills={[
              { key: "1", label: "Today" },
              { key: "7", label: "7 days" },
              { key: "30", label: "30 days" },
            ]}
            active={String(days)}
            onChange={(k) => setDays(Number(k))}
          />
        </div>

        <div className="flex-1 overflow-y-auto px-8 pb-10">
          {/* System health — one slim strip; details stay in banners below */}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-md border border-line bg-surface px-4 py-2.5">
            <span className="text-[13px] font-semibold text-ink">System health</span>
            {health ? (
              <>
                <HealthItem tone={health.database === "connected" ? "ok" : "bad"}>
                  Database {health.database}
                </HealthItem>
                <HealthItem tone={health.providers > 0 ? "ok" : "bad"}>
                  {health.providers} provider{health.providers === 1 ? "" : "s"}
                </HealthItem>
                <HealthItem tone={health.agents > 0 ? "ok" : "warn"}>
                  {health.agents} agent{health.agents === 1 ? "" : "s"}
                </HealthItem>
                <HealthItem tone={health.active_runs > 0 ? "ok" : "warn"}>
                  {health.active_runs} active run{health.active_runs === 1 ? "" : "s"}
                </HealthItem>
                {health.sandbox ? (
                  <HealthItem
                    tone={
                      health.sandbox.state === "available"
                        ? "ok"
                        : health.sandbox.state === "experimental"
                          ? "warn"
                          : "warn"
                    }
                  >
                    Sandbox:{" "}
                    {health.sandbox.state === "available"
                      ? health.sandbox.kind
                      : health.sandbox.state === "experimental"
                        ? `${health.sandbox.kind} (experimental)`
                        : "off"}
                  </HealthItem>
                ) : null}
              </>
            ) : (
              <span className="text-[13px] text-ink-faint">
                {healthFailed ? "Health data unavailable — check the gateway." : "Checking…"}
              </span>
            )}
            {healthFailed && (
              <button
                type="button"
                onClick={() => void fetchHealth()}
                className="cursor-pointer text-[13px] text-ink-muted underline-offset-2 hover:text-ink hover:underline"
              >
                Retry
              </button>
            )}
          </div>

          {/* Honesty banners — version skew, experimental/unverified sandbox,
              unavailable sandbox + one-time setup */}
          {health?.version && health.version !== __APP_VERSION__ ? (
            <WarningBanner tone="danger" className="mt-3" title="Version mismatch">
              This app is {__APP_VERSION__} but its gateway is {health.version}. An update
              replaced the app but not its bundled gateway — reinstall CaberOS before
              relying on this session; the two halves may disagree about the database
              schema.
            </WarningBanner>
          ) : null}
          {health?.sandbox?.state === "experimental" ? (
            <WarningBanner tone="warning" className="mt-3" title="Sandbox not yet verified">
              {health.sandbox.kind} executes shell commands, but is not yet a verified
              security boundary. {health.sandbox.reason}
            </WarningBanner>
          ) : null}
          {health?.sandbox?.state === "unavailable" ? (
            <WarningBanner tone="warning" className="mt-3" title="Shell sandbox is off">
              {health.sandbox.setup_required && isDesktop ? (
                <>
                  Agents cannot run shell commands until a one-time setup — Windows asks
                  for permission once, then commands run in a restricted sandbox.
                  <span className="mt-2 flex items-center gap-3">
                    <Button
                      size="sm"
                      disabled={setupBusy}
                      onClick={() => void enableShellSandbox()}
                    >
                      {setupBusy ? "Waiting for Windows…" : "Enable shell sandbox"}
                    </Button>
                    {setupError && <span className="text-[12px] text-danger">{setupError}</span>}
                  </span>
                </>
              ) : (
                <>Agents cannot run shell commands on this machine. {health.sandbox.reason}</>
              )}
              <span className="mt-1 block text-[12px] text-ink-faint">
                Every other capability — files, web, memory, skills, knowledge and MCP
                tools — is unaffected.
              </span>
            </WarningBanner>
          ) : null}

          {statsFailed && (
            <WarningBanner
              tone="danger"
              className="mt-4"
              title="Overview didn't load"
              action={
                <Button variant="outline" size="sm" onClick={refresh}>
                  Retry
                </Button>
              }
            >
              Check the gateway and try again.
            </WarningBanner>
          )}

          {stats ? (
            <>
              {/* Failed-runs banner — only when the window has failures */}
              {stats.error_count > 0 && (
                <WarningBanner
                  tone="danger"
                  className="mt-4"
                  action={
                    <button
                      type="button"
                      onClick={() =>
                        navigate(
                          failingAgents.length === 1
                            ? `/traces/${failingAgents[0].agent_id}?status=failed`
                            : "/traces",
                        )
                      }
                      className="cursor-pointer whitespace-nowrap text-[13px] font-medium text-danger underline-offset-2 hover:underline"
                    >
                      Review failed runs →
                    </button>
                  }
                >
                  <span className="font-semibold text-ink">
                    {stats.error_count} of {stats.total_runs} runs failed
                  </span>{" "}
                  in the last {windowLabel}
                  {failingAgents.length > 0 &&
                    ` — ${failingAgents.length === 1 ? "all from " : "from "}${failingAgents
                      .map((a) => a.agent_name || agentName(a.agent_id))
                      .join(", ")}`}
                  .
                </WarningBanner>
              )}

              {/* Stat cards */}
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                <StatCard label="Total runs" value={stats.total_runs.toLocaleString()} sublabel={windowLabel} />
                <StatCard
                  label="Error rate"
                  value={
                    <span className={stats.error_count > 0 ? "text-danger" : undefined}>
                      {stats.error_rate}%
                    </span>
                  }
                  sublabel={`${stats.error_count} failed`}
                />
                <StatCard
                  label="Total tokens"
                  value={stats.total_tokens.toLocaleString()}
                  sublabel="in + out"
                />
                <StatCard label="Total cost" value={fmtCost(stats.total_cost)} sublabel={windowLabel} />
                <StatCard
                  label="Avg latency"
                  value={
                    stats.avg_latency_ms > 1000
                      ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s`
                      : `${stats.avg_latency_ms}ms`
                  }
                  sublabel="per run"
                />
              </div>

              {/* Charts */}
              <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <SectionCard title="Runs per day">
                  <BarChart
                    data={stats.time_series.map((t) => ({
                      label: fmtDay(t.date),
                      value: t.runs,
                      maxValue: maxRuns,
                      formatted: `${t.runs}`,
                    }))}
                  />
                </SectionCard>
                <SectionCard title="Cost per day">
                  {anyCost ? (
                    <BarChart
                      data={stats.time_series.map((t) => ({
                        label: fmtDay(t.date),
                        value: t.cost,
                        maxValue: maxCost,
                        formatted: fmtCost(t.cost),
                      }))}
                    />
                  ) : (
                    <div className="flex h-36 items-center justify-center text-[13px] text-ink-faint">
                      No billable usage in this range
                    </div>
                  )}
                </SectionCard>
              </div>

              {/* Top agents + recent runs */}
              <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <SectionCard
                  title={
                    <span className="flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-accent" />
                      Top agents
                    </span>
                  }
                  bodyClassName="px-0 py-0"
                >
                  {stats.by_agent.length === 0 ? (
                    <p className="px-4 py-6 text-center text-[13px] text-ink-faint">No agent activity</p>
                  ) : (
                    <div className="divide-y divide-line">
                      {stats.by_agent.slice(0, 5).map((a) => {
                        const ok = a.run_count - a.error_count;
                        const okPct = a.run_count > 0 ? (ok / a.run_count) * 100 : 0;
                        return (
                          <button
                            key={a.agent_id}
                            type="button"
                            onClick={() => navigate(`/traces/${a.agent_id}`)}
                            className="block w-full cursor-pointer px-4 py-3 text-left transition-colors hover:bg-sunken/60"
                          >
                            <span className="flex items-baseline justify-between gap-2">
                              <span className="truncate text-[14px] font-semibold text-ink">
                                {a.agent_name || agentName(a.agent_id)}
                              </span>
                              <span className="shrink-0 text-[12px] text-ink-muted">
                                {a.run_count} run{a.run_count === 1 ? "" : "s"} · {fmtCost(a.total_cost)}
                              </span>
                            </span>
                            <span className="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-track">
                              <span className="h-full bg-accent" style={{ width: `${okPct}%` }} />
                              {a.error_count > 0 && (
                                <span className="h-full bg-danger" style={{ width: `${100 - okPct}%` }} />
                              )}
                            </span>
                            <span className="mt-1.5 block text-[12px] text-ink-faint">
                              {ok} succeeded{a.error_count > 0 ? ` · ${a.error_count} failed` : ""}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </SectionCard>

                <SectionCard
                  title="Recent runs"
                  bodyClassName="px-0 py-0"
                  action={
                    <button
                      type="button"
                      onClick={() => navigate("/traces")}
                      className="cursor-pointer text-[13px] text-ink-muted transition-colors hover:text-ink"
                    >
                      View all →
                    </button>
                  }
                >
                  {stats.recent_runs.length === 0 ? (
                    <p className="px-4 py-6 text-center text-[13px] text-ink-faint">No recent runs</p>
                  ) : (
                    <div className="divide-y divide-line">
                      {stats.recent_runs.slice(0, 6).map((r) => {
                        const st = RUN_STATUS[r.status] ?? {
                          kind: "idle" as StatusKind,
                          label: r.status.charAt(0).toUpperCase() + r.status.slice(1),
                        };
                        return (
                          <button
                            key={r.id}
                            type="button"
                            onClick={() => navigate(`/traces/${r.agent_id}/${r.id}`)}
                            className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-sunken/60"
                          >
                            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
                              {r.agent_name || agentName(r.agent_id)}
                            </span>
                            <StatusWord status={st.kind} label={st.label} />
                            <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-faint">
                              {(r.tokens_in + r.tokens_out).toLocaleString()} tok
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </SectionCard>
              </div>

              {/* Spend — agent totals vs the model-call ledger */}
              <SpendSection days={days} agents={agents} />
            </>
          ) : !statsFailed ? (
            <div className="py-20 text-center">
              <p className="text-[14px] text-ink-faint">Loading dashboard…</p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// --- Local components ---

function HealthItem({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "bad";
  children: React.ReactNode;
}) {
  const dot = tone === "ok" ? "bg-success" : tone === "warn" ? "bg-warning" : "bg-danger";
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] leading-[18px] text-ink-muted">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  );
}

/** Accent bars with a value label on top and a baseline tick for empty days. */
function BarChart({
  data,
}: {
  data: { label: string; value: number; maxValue: number; formatted: string }[];
}) {
  const step = data.length <= 10 ? 1 : Math.ceil(data.length / 10);
  return (
    <div className="flex h-36 items-end gap-1.5">
      {data.map((d, i) => {
        const pct = d.maxValue > 0 ? (d.value / d.maxValue) * 100 : 0;
        return (
          <div
            key={i}
            className="group flex h-full flex-1 flex-col items-center justify-end"
            title={`${d.label}: ${d.formatted}`}
          >
            {d.value > 0 && (
              <span className="mb-1 text-[11px] font-medium leading-none text-ink">{d.formatted}</span>
            )}
            <div
              className="w-2/3 max-w-11 rounded-sm"
              style={{
                height: d.value > 0 ? `${Math.max(pct, 6)}%` : 3,
                background: d.value > 0 ? "var(--accent)" : "var(--track)",
              }}
            />
            <span className="mt-1.5 h-4 text-[10px] leading-4 text-ink-faint">
              {i % step === 0 ? d.label : ""}
            </span>
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

  const fieldClass =
    "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink";
  const select = (
    key: keyof SpendDraft,
    label: string,
    options: { value: string; label: string }[],
    allLabel: string,
  ) => (
    <label className="flex items-center gap-1.5" key={key}>
      <span className="text-[11px] text-[var(--ink-3)]">{label}</span>
      <Select
        value={filters[key]}
        onChange={(v) => setFilters({ ...filters, [key]: v })}
        options={[{ value: "", label: allLabel }, ...options]}
        className={fieldClass}
        align="left"
      />
    </label>
  );

  return (
    <SectionCard
      className="mt-4"
      title="Spend"
      action={
        <FilterPills
          pills={[
            { key: "agent", label: "Agent" },
            { key: "platform", label: "Platform" },
          ]}
          active={scope}
          onChange={(k) => setScope(k as "agent" | "platform")}
          variant="segmented"
        />
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className="flex items-center gap-1.5">
          <span className="text-[11px] text-[var(--ink-3)]">Agent</span>
          <Select
            value={filters.agent_id}
            onChange={(v) => setFilters({ ...filters, agent_id: v })}
            options={[
              { value: "", label: "All agents" },
              ...agents.map((a) => ({ value: a.id, label: a.name })),
            ]}
            className={fieldClass}
            align="left"
          />
        </label>
        {scope === "platform" && (
          <>
            {select(
              "provider_id",
              "Provider",
              Object.entries(providerNames).map(([id, name]) => ({ value: id, label: name })),
              "All providers",
            )}
            <label className="flex items-center gap-1.5">
              <span className="text-[11px] text-[var(--ink-3)]">Model</span>
              <input
                value={filters.model}
                onChange={(e) => setFilters({ ...filters, model: e.target.value })}
                placeholder="Any model"
                className={`${fieldClass} w-40`}
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
        <Button
          size="sm"
          onClick={() => setApplied({ ...filters })}
        >
          Apply
        </Button>
      </div>

      {loading && <p className="text-[12px] text-[var(--ink-3)]">Loading spend…</p>}
      {error && !loading && (
        <p className="text-[12px] text-danger">{error}</p>
      )}
      {!loading && !error && !visible && (
        <p className="text-[12px] text-[var(--ink-3)]">No spend data for this selection.</p>
      )}

      {!loading && !error && visible?.scope === "agent" && (
        <div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="Total" value={fmtCost(visible.data.total_cost)} />
            <Metric label="Runs" value={String(visible.data.total_runs)} />
            <Metric label="Tokens in" value={visible.data.total_tokens_in.toLocaleString()} />
            <Metric label="Tokens out" value={visible.data.total_tokens_out.toLocaleString()} />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="overflow-x-auto">
              <p className="mb-1 text-[11px] uppercase tracking-[0.05em] text-[var(--ink-3)]">By agent</p>
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left text-[11px] text-[var(--ink-3)]">
                    <th className="pb-1 font-normal">Agent</th>
                    <th className="pb-1 text-right font-normal">Runs</th>
                    <th className="pb-1 text-right font-normal">Tokens</th>
                    <th className="pb-1 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.data.by_agent.map((r) => (
                    <tr key={r.agent_id} className="border-t border-line last:border-0">
                      <td className="py-1.5 pr-2 font-medium text-ink">{r.agent_name || agentName(r.agent_id)}</td>
                      <td className="py-1.5 text-right tabular-nums">{r.run_count}</td>
                      <td className="py-1.5 text-right tabular-nums text-[var(--ink-3)]">{(r.tokens_in + r.tokens_out).toLocaleString()}</td>
                      <td className="py-1.5 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
                    </tr>
                  ))}
                  {visible.data.by_agent.length === 0 && (
                    <tr><td className="py-1.5 text-[var(--ink-3)]" colSpan={4}>none</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto">
              <p className="mb-1 text-[11px] uppercase tracking-[0.05em] text-[var(--ink-3)]">By trigger</p>
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left text-[11px] text-[var(--ink-3)]">
                    <th className="pb-1 font-normal">Trigger</th>
                    <th className="pb-1 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(visible.data.by_trigger).map(([trigger, cost]) => (
                    <tr key={trigger} className="border-t border-line last:border-0">
                      <td className="py-1.5">{trigger}</td>
                      <td className="py-1.5 text-right tabular-nums">{fmtCost(cost)}</td>
                    </tr>
                  ))}
                  {Object.keys(visible.data.by_trigger).length === 0 && (
                    <tr><td className="py-1.5 text-[var(--ink-3)]" colSpan={2}>none</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <p className="mt-3 border-t border-line pt-2 text-[11px] text-[var(--ink-3)]">
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
        <p className="mt-3 border-t border-line pt-2 text-[11px] text-[var(--ink-3)]">
          Ledger calls only — pre-ledger runs aren't reconstructed, test
          runs are excluded, and runless/deleted-run calls are included.
          Agent totals and platform totals count different things.
        </p>
      )}
    </SectionCard>
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
      <div className="mt-4 overflow-x-auto">
        <p className="mb-1 text-[11px] uppercase tracking-[0.05em] text-[var(--ink-3)]">By model</p>
        <table className="w-full min-w-[600px] text-[12px]">
          <thead>
            <tr className="text-left text-[11px] text-[var(--ink-3)]">
              <th className="w-[26%] pb-1 font-normal">Model</th>
              <th className="w-[24%] pb-1 font-normal">Provider</th>
              <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Calls</th>
              <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Recorded cost</th>
              <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Pricing</th>
              <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Thinking</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model.map((r, i) => (
              <tr key={`${r.provider_id}/${r.model_name}/${i}`} className="border-t border-line last:border-0">
                <td className="max-w-0 truncate px-2 py-1.5 font-medium text-[var(--ink)]" title={r.model_name ?? undefined}>
                  {r.model_name ?? "unknown model"}
                </td>
                <td className="max-w-0 truncate px-2 py-1.5 text-[var(--ink-2)]" title={r.provider_id ?? undefined}>
                  {providerLabel(r.provider_id, providerNames)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{r.call_count}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right"><PricingCoverage row={r} /></td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums text-[var(--ink-3)]">
                  {r.thinking_tokens == null ? "Not reported" : r.thinking_tokens.toLocaleString()}
                </td>
              </tr>
            ))}
            {data.by_model.length === 0 && (
              <tr><td className="py-1.5 text-[var(--ink-3)]" colSpan={6}>none</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* By provider / by kind — side by side only when wide enough */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
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
      <p className="mb-1 text-[11px] uppercase tracking-[0.05em] text-[var(--ink-3)]">{title}</p>
      <table className="w-full min-w-[480px] text-[12px]">
        <thead>
          <tr className="text-left text-[11px] text-[var(--ink-3)]">
            <th className="w-[40%] pb-1 font-normal">Name</th>
            <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Calls</th>
            <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Recorded cost</th>
            <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Pricing</th>
            <th className="whitespace-nowrap px-2 pb-1 text-right font-normal">Thinking</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line last:border-0">
              <td className="max-w-0 truncate px-2 py-1.5" title={titleAttr?.(r) ?? label(r)}>{label(r)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{r.call_count}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{fmtCost(r.total_cost)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right"><PricingCoverage row={r} /></td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums text-[var(--ink-3)]">
                {r.thinking_tokens == null ? "Not reported" : r.thinking_tokens.toLocaleString()}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td className="py-1.5 text-[var(--ink-3)]" colSpan={5}>none</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.05em] text-[var(--ink-3)]">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-[var(--ink)]">{value}</p>
    </div>
  );
}
