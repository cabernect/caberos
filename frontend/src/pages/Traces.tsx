import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Download, Plus, X } from "lucide-react";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { FilterPills } from "@/components/ui/filter-pills";
import { WarningBanner } from "@/components/ui/warning-banner";
import { StatusWord, type StatusKind } from "@/components/ui/status-word";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Agent, RunSummary, RunDetail, RunFilters, DashboardStats } from "@/lib/types";
import { RunTimeline } from "@/components/RunTimeline";
import { RunMessages } from "@/components/RunMessages";
import { RunSyscalls } from "@/components/RunSyscalls";
import { Select } from "@/components/ui/select";
import { formatClock } from "@/lib/time";

const RUN_STATUS: Record<string, { kind: StatusKind; label: string }> = {
  completed: { kind: "success", label: "Completed" },
  failed: { kind: "failed", label: "Failed" },
  running: { kind: "running", label: "Running" },
  awaiting_approval: { kind: "paused", label: "Awaiting approval" },
  stopped: { kind: "idle", label: "Stopped" },
  interrupted: { kind: "idle", label: "Interrupted" },
};

const SHARE_STEPS = [100, 72, 50, 32, 18, 10];
const RUNS_PAGE_SIZE = 50;

export function Traces() {
  const { agentId, runId } = useParams();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);

  // Runs state
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  // Cluster detection reads a dedicated failed-only window — the paged list
  // would miss bursts older than the first page.
  const [clusterSource, setClusterSource] = useState<RunSummary[]>([]);
  // Draft controls — nothing queries until Apply. A `?status=` param seeds
  // both draft and applied so deep links (e.g. "Review failed runs") filter.
  const [searchParams] = useSearchParams();
  const urlStatus = searchParams.get("status") || undefined;
  const [draftFilters, setDraftFilters] = useState<RunFilters>(urlStatus ? { status: urlStatus } : {});
  const [appliedFilters, setAppliedFilters] = useState<RunFilters>(urlStatus ? { status: urlStatus } : {});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const runsSeq = useRef(0);

  // Run detail state
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [detailView, setDetailView] = useState<"timeline" | "messages">("timeline");
  const [providerNames, setProviderNames] = useState<Record<string, string>>({});
  const [egressCaps, setEgressCaps] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const detailSeq = useRef(0);
  const ctxRef = useRef<HTMLDetailsElement>(null);

  // Route param changes don't remount — re-seed when the URL param changes.
  useEffect(() => {
    if (!urlStatus) return;
    setDraftFilters((f) => ({ ...f, status: urlStatus }));
    setAppliedFilters((f) => ({ ...f, status: urlStatus }));
  }, [urlStatus]);

  const fetchAgents = useCallback(async () => {
    try {
      setAgents(await api.listAgents());
    } catch {}
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      setStats(await api.getDashboardStats(30));
    } catch {}
  }, []);

  const fetchRuns = useCallback(async (offset = 0, append = false) => {
    const seq = ++runsSeq.current;
    if (append) setLoadingMore(true);
    else setLoadingRuns(true);
    setRunsError(null);
    try {
      const data = await api.listRuns({
        agent_id: agentId,   // optional — absent means all agents
        is_test: false,
        limit: RUNS_PAGE_SIZE,
        offset,
        ...appliedFilters,
      });
      if (seq === runsSeq.current) {
        setRuns((prev) => (append ? [...prev, ...data] : data));
        setHasMore(data.length === RUNS_PAGE_SIZE);
      }
    } catch {
      if (seq === runsSeq.current && !append) {
        setRuns([]);
        setRunsError("Couldn't load runs — check the filter values.");
      }
    } finally {
      if (seq === runsSeq.current) {
        setLoadingRuns(false);
        setLoadingMore(false);
      }
    }
  }, [agentId, appliedFilters]);

  const fetchRunDetail = useCallback(async () => {
    if (!runId) return;
    const my = ++detailSeq.current;
    setRunDetail(null); // clear the previous run before the fetch lands
    try {
      const data = await api.getRunDetail(runId);
      if (my === detailSeq.current) setRunDetail(data);
    } catch {
      if (my === detailSeq.current) setRunDetail(null);
    }
  }, [runId]);

  useEffect(() => {
    fetchAgents();
    fetchStats();
  }, [fetchAgents, fetchStats]);

  useEffect(() => {
    if (!runId) void fetchRuns(0, false);
  }, [runId, fetchRuns]);

  // Failed-only window for burst detection (scoped to the agent filter).
  useEffect(() => {
    if (runId) return;
    let alive = true;
    api
      .listRuns({ agent_id: agentId, is_test: false, status: "failed", limit: 100, offset: 0 })
      .then((d) => { if (alive) setClusterSource(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [runId, agentId]);

  useEffect(() => {
    if (runId) fetchRunDetail();
  }, [runId, fetchRunDetail]);

  // Provider display names for the trace — best-effort, failures keep
  // the trace usable with raw ids.
  useEffect(() => {
    api
      .listProviders()
      .then((providers) => {
        setProviderNames(
          Object.fromEntries(providers.map((p) => [p.id, p.name])),
        );
      })
      .catch(() => {});
    // Registry egress flags power the syscalls "left this machine" count.
    api
      .listCapabilities()
      .then((caps) =>
        setEgressCaps(new Set(caps.filter((c) => c.egress).map((c) => c.name))),
      )
      .catch(() => {});
  }, []);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  const fmtCost = (c: number) => (c < 0.01 ? `$${c.toFixed(6)}` : `$${c.toFixed(4)}`);
  const fmtDate = (d: string) => new Date(d).toLocaleString();
  const fmtStarted = (d: string) => {
    const dt = new Date(d);
    return `${dt.toLocaleDateString("en-US", { month: "short", day: "numeric" })} · ${formatClock(d)}`;
  };
  const fmtLatency = (ms: number) =>
    ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)} ms`;

  const activeAgent = agentId ? agents.find((a) => a.id === agentId) : null;
  const statusFilter = appliedFilters.status ?? "";
  const maxLatency = Math.max(1, ...runs.map((r) => r.latency_ms));
  const lastRun = stats?.recent_runs[0] ?? null;
  const errorAgents = stats?.by_agent.filter((a) => a.error_count > 0).length ?? 0;

  // Largest burst of same-trigger failures inside one day, consecutive
  // gaps under 10 minutes — a config problem signature, not model error.
  const failureCluster = useMemo(() => {
    if (statusFilter === "failed") return null;
    const dayKey = (iso: string) => {
      const d = new Date(iso);
      const p = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    };
    const failed = [...clusterSource].sort((a, b) => a.started_at.localeCompare(b.started_at));
    let best: RunSummary[] = [];
    for (const r of failed) {
      const day = dayKey(r.started_at);
      const same = failed.filter((x) => x.trigger === r.trigger && dayKey(x.started_at) === day);
      let cluster = [same[0]];
      for (let i = 1; i < same.length; i++) {
        const gap = new Date(same[i].started_at).getTime() - new Date(same[i - 1].started_at).getTime();
        if (gap <= 10 * 60 * 1000) cluster.push(same[i]);
        else cluster = [same[i]];
        if (cluster.length > best.length) best = [...cluster];
      }
    }
    return best.length >= 3 ? best : null;
  }, [clusterSource, statusFilter]);
  // Dismissal is keyed to this cluster's first/last run ids — a different
  // cluster (or the same one after new failures shift it) resurfaces.
  const [dismissedCluster, setDismissedCluster] = useState<string | null>(null);
  const clusterKey = failureCluster
    ? `${failureCluster[0].id}:${failureCluster[failureCluster.length - 1].id}`
    : null;

  // Quick-chip option sets — honest sources: triggers seen in the loaded run
  // set, models the configured agents actually run on.
  const triggerOptions = useMemo(
    () =>
      [...new Set([...runs.map((r) => r.trigger), ...(appliedFilters.trigger ? [appliedFilters.trigger] : [])])]
        .sort()
        .map((t) => ({ key: t, label: t })),
    [runs, appliedFilters.trigger],
  );
  const modelOptions = useMemo(
    () =>
      [...new Set([...agents.map((a) => a.model).filter((m): m is string => !!m), ...(appliedFilters.model ? [appliedFilters.model] : [])])]
        .sort()
        .map((m) => ({ key: m, label: m })),
    [agents, appliedFilters.model],
  );
  const applyQuick = (patch: Partial<RunFilters>) => {
    const next: RunFilters = { ...appliedFilters };
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) delete (next as Record<string, unknown>)[k];
      else (next as Record<string, unknown>)[k] = v;
    }
    setAppliedFilters(next);
    setDraftFilters(next);
  };
  const pickDate = (key: string | null) => {
    if (!key) return applyQuick({ since: undefined, until: undefined });
    const since = new Date();
    if (key === "today") since.setHours(0, 0, 0, 0);
    else if (key === "7d") since.setDate(since.getDate() - 7);
    else since.setDate(since.getDate() - 30);
    applyQuick({ since: since.toISOString(), until: undefined });
  };
  const dateChipLabel = appliedFilters.since
    ? `since ${new Date(appliedFilters.since).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
    : undefined;
  const providerOptions = useMemo(
    () =>
      Object.entries(providerNames)
        .map(([id, name]) => ({ key: id, label: name }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [providerNames],
  );
  const activeFilterCount = useMemo(
    () => Object.values(appliedFilters).filter((v) => v !== undefined && v !== "").length,
    [appliedFilters],
  );

  const [exportOpen, setExportOpen] = useState(false);

  const download = (name: string, blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportCsv = () => {
    const rows = [
      "run_id,agent,status,trigger,tokens_in,tokens_out,cost_usd,latency_ms,started_at,error",
      ...runs.map((r) =>
        [
          r.id,
          `"${(r.agent_name || r.agent_id).replace(/"/g, '""')}"`,
          r.status,
          r.trigger,
          r.tokens_in,
          r.tokens_out,
          r.cost,
          r.latency_ms,
          r.started_at,
          `"${(r.error ?? "").replace(/"/g, '""').replace(/\n/g, " ")}"`,
        ].join(","),
      ),
    ];
    download(`caberos-traces${agentId ? `-${agentId}` : ""}.csv`, new Blob([rows.join("\n")], { type: "text/csv" }));
  };

  const exportJson = () => {
    download(
      `caberos-traces${agentId ? `-${agentId}` : ""}.json`,
      new Blob([JSON.stringify(runs, null, 2)], { type: "application/json" }),
    );
  };

  const copyLink = () => {
    void navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const inShare =
    runDetail && runDetail.tokens_in + runDetail.tokens_out > 0
      ? runDetail.tokens_in / (runDetail.tokens_in + runDetail.tokens_out)
      : 0;

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="traces"
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {runId && runDetail ? (
          <PageHeader
            breadcrumbs={[
              { label: "Observability" },
              { label: "Traces", onClick: () => navigate("/traces") },
              { label: runDetail.agent_name || agentName(runDetail.agent_id), onClick: () => navigate(`/traces/${runDetail.agent_id}`) },
              { label: runDetail.id.slice(0, 8) },
            ]}
            title={`Run ${runDetail.id.slice(0, 8)}`}
            subtitle={
              <span className="inline-flex items-center gap-1.5">
                <StatusWord
                  status={RUN_STATUS[runDetail.status]?.kind ?? "idle"}
                  label={RUN_STATUS[runDetail.status]?.label ?? runDetail.status}
                />
                <span className="text-ink-faint">
                  · {runDetail.agent_name || agentName(runDetail.agent_id)} · {runDetail.trigger} ·{" "}
                  {fmtDate(runDetail.started_at)}
                </span>
              </span>
            }
            actions={
              <>
                <Button variant="outline" size="sm" onClick={copyLink}>
                  {copied ? "Copied" : "Copy link"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    navigate(`/agents/${runDetail.agent_id}/chat?session=${runDetail.session_id}`)
                  }
                >
                  Open in chat
                </Button>
              </>
            }
          />
        ) : (
          <PageHeader
            breadcrumbs={[{ label: "Observability" }, { label: "Traces" }]}
            title="Traces"
            subtitle="Every run across your agents, with full detail one click away."
            actions={
              <div className="relative">
                <Button variant="outline" size="sm" onClick={() => setExportOpen((v) => !v)} disabled={runs.length === 0}>
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
                        onClick={() => {
                          setExportOpen(false);
                          void api.exportRunsXlsx({ agent_id: agentId, is_test: false, ...appliedFilters });
                        }}
                        className="w-full cursor-pointer px-3 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                      >
                        Excel (.xlsx)
                      </button>
                    </div>
                  </>
                )}
              </div>
            }
          />
        )}

        {!runId && (
          <div className="px-8 pt-4">
            <PageIntro def={INTRO_BY_KEY.traces} />
          </div>
        )}

        {/* --- Runs list header zone — stats, share bar, and filter pills stay pinned --- */}
        {!runId && (
          <div className="px-8 pb-4">
              {/* Stat cards */}
              {stats && (
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <StatCard
                    label="Runs"
                    value={stats.total_runs.toLocaleString()}
                    sublabel={`${stats.by_agent.length} agent${stats.by_agent.length === 1 ? "" : "s"}`}
                  />
                  <StatCard
                    label="Errors"
                    value={
                      <span className={stats.error_count > 0 ? "text-danger" : undefined}>
                        {stats.error_count}
                      </span>
                    }
                    sublabel={errorAgents > 0 ? `across ${errorAgents} agent${errorAgents === 1 ? "" : "s"}` : "none"}
                  />
                  <StatCard label="Cost" value={fmtCost(stats.total_cost)} sublabel="all agents" />
                  <StatCard
                    label="Last run"
                    value={
                      lastRun
                        ? new Date(lastRun.started_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                          })
                        : "—"
                    }
                    sublabel={
                      lastRun
                        ? `${formatClock(lastRun.started_at)} · ${lastRun.agent_name || agentName(lastRun.agent_id)}`
                        : "no runs yet"
                    }
                  />
                </div>
              )}

              {/* Agent share bar */}
              {stats && stats.total_runs > 0 && (
                <div className="mt-4 rounded-md border border-line bg-surface px-4 py-3">
                  <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full">
                    {stats.by_agent.map((a, i) => (
                      <div
                        key={a.agent_id}
                        className="h-full first:rounded-l-full last:rounded-r-full"
                        style={{
                          width: `${(a.run_count / stats.total_runs) * 100}%`,
                          background: `color-mix(in srgb, var(--accent) ${SHARE_STEPS[Math.min(i, SHARE_STEPS.length - 1)]}%, var(--surface))`,
                        }}
                        title={`${a.agent_name || agentName(a.agent_id)}: ${a.run_count} runs`}
                      />
                    ))}
                  </div>
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1">
                    {stats.by_agent.map((a, i) => (
                      <button
                        key={a.agent_id}
                        type="button"
                        onClick={() => navigate(`/traces/${a.agent_id}`)}
                        className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] text-ink-muted transition-colors hover:text-ink"
                      >
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{
                            background: `color-mix(in srgb, var(--accent) ${SHARE_STEPS[Math.min(i, SHARE_STEPS.length - 1)]}%, var(--surface))`,
                          }}
                        />
                        {a.agent_name || agentName(a.agent_id)}{" "}
                        <span className="font-medium text-ink">{a.run_count}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Status pills + filter chips */}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <FilterPills
                  variant="segmented"
                  pills={[
                    { key: "", label: "All" },
                    { key: "completed", label: "Completed" },
                    { key: "failed", label: "Failed", count: stats?.error_count },
                  ]}
                  active={statusFilter}
                  onChange={(k) => {
                    const next = { ...appliedFilters, status: k || undefined };
                    setAppliedFilters(next);
                    setDraftFilters(next);
                  }}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <QuickFilterChip
                    label="Agent"
                    active={activeAgent?.name}
                    activeKey={agentId}
                    options={agents.map((a) => ({ key: a.id, label: a.name }))}
                    onPick={(id) => navigate(id ? `/traces/${id}` : "/traces")}
                  />
                  <QuickFilterChip
                    label="Trigger"
                    active={appliedFilters.trigger}
                    options={triggerOptions}
                    onPick={(v) => applyQuick({ trigger: v ?? undefined })}
                  />
                  <QuickFilterChip
                    label="Model"
                    active={appliedFilters.model}
                    options={modelOptions}
                    onPick={(v) => applyQuick({ model: v ?? undefined })}
                  />
                  <QuickFilterChip
                    label="Date"
                    active={dateChipLabel}
                    options={DATE_OPTIONS}
                    onPick={pickDate}
                  />
                  <Button variant="outline" size="sm" onClick={() => setFiltersOpen((v) => !v)}>
                    <Plus className="h-3.5 w-3.5" />
                    Filter
                  </Button>
                </div>
              </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-8 pb-10">
          {/* --- Run detail view --- */}
          {runId && (
            !runDetail ? (
              <p className="py-20 text-center text-[14px] text-ink-faint">Loading run…</p>
            ) : (
              <>
                {/* Stat cards */}
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <StatCard label="Duration" value={fmtLatency(runDetail.latency_ms)} />
                  <StatCard
                    label="Tokens"
                    value={(runDetail.tokens_in + runDetail.tokens_out).toLocaleString()}
                    sublabel={`${runDetail.tokens_in.toLocaleString()} in · ${runDetail.tokens_out.toLocaleString()} out`}
                  />
                  <StatCard
                    label="Tool calls"
                    value={runDetail.audit_records.length}
                    sublabel={topCapability(runDetail.audit_records)}
                  />
                  <StatCard label="Cost" value={fmtCost(runDetail.cost)} />
                </div>

                {/* Context-share insight → opens the pinned-config details */}
                {inShare >= 0.9 && (
                  <p className="mt-3 flex flex-wrap items-center gap-x-2 text-[13px] text-ink-muted">
                    <span>
                      ✧ {Math.round(inShare * 100)}% of tokens were input — a large context was
                      sent on this run.
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        const el = ctxRef.current;
                        if (el) {
                          el.open = true;
                          el.scrollIntoView({ behavior: "smooth", block: "center" });
                        }
                      }}
                      className="cursor-pointer font-medium text-accent hover:underline"
                    >
                      Context &amp; pinned configuration ›
                    </button>
                  </p>
                )}

                <RunTraceView
                  providerNames={providerNames}
                  egressCaps={egressCaps}
                  run={runDetail}
                  view={detailView}
                  onViewChange={setDetailView}
                  ctxRef={ctxRef}
                />
              </>
            )
          )}

          {/* --- Runs list view (all agents, flat) --- */}
          {!runId && (
            <>
              {/* Filter panel — draft controls, nothing queries until Apply */}
              {filtersOpen && (
                <div className="mt-3 rounded-lg border border-line bg-surface p-4">
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                    <FilterSelect label="Provider" value={draftFilters.provider_id ?? ""}
                      options={providerOptions}
                      onChange={(v) => setDraftFilters({ ...draftFilters, provider_id: v || undefined })} />
                    <FilterInput label="Model" value={draftFilters.model ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, model: v || undefined })} />
                    <FilterInput label="Purpose" value={draftFilters.purpose ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, purpose: v || undefined })} />
                    <FilterInput label="Kind" value={draftFilters.kind ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, kind: v || undefined })} />
                    <FilterSelect label="Status" value={draftFilters.status ?? ""}
                      options={STATUS_OPTIONS}
                      onChange={(v) => setDraftFilters({ ...draftFilters, status: v || undefined })} />
                    <FilterInput label="Trigger" value={draftFilters.trigger ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, trigger: v || undefined })} />
                  </div>
                  {advancedOpen && (
                    <div className="mt-3 grid grid-cols-2 gap-3 border-t border-line pt-3 sm:grid-cols-3 lg:grid-cols-6">
                      <FilterInput label="Schedule ID" value={draftFilters.schedule_id ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, schedule_id: v || undefined })} />
                      <FilterInput label="Channel" value={draftFilters.channel ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, channel: v || undefined })} />
                      <FilterInput label="Capability" value={draftFilters.capability ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, capability: v || undefined })} />
                      <FilterSelect label="Tool status" value={draftFilters.tool_status ?? ""}
                        options={["complete", "denied", "failed", "timeout", "interrupted", "pending_approval", "running"].map((o) => ({ key: o, label: o }))}
                        onChange={(v) => setDraftFilters({ ...draftFilters, tool_status: v || undefined })} />
                      <FilterInput label="Effect" value={draftFilters.effect ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, effect: v || undefined })} />
                      <FilterInput label="Browser profile" placeholder="name or ID" value={draftFilters.browser_profile ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, browser_profile: v || undefined })} />
                      <FilterInput label="Artifact format" value={draftFilters.artifact_format ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, artifact_format: v || undefined })} />
                      <FilterInput label="Retrieval mode" value={draftFilters.retrieval_mode ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, retrieval_mode: v || undefined })} />
                      <FilterSelect label="Retrieval degraded" value={draftFilters.retrieval_degraded === undefined ? "" : String(draftFilters.retrieval_degraded)}
                        options={[{ key: "true", label: "yes" }, { key: "false", label: "no" }]}
                        onChange={(v) => setDraftFilters({ ...draftFilters, retrieval_degraded: v === "" ? undefined : v === "true" })} />
                      <FilterInput label="Since" placeholder="ISO date" value={draftFilters.since ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, since: v || undefined })} />
                      <FilterInput label="Until" placeholder="ISO date" value={draftFilters.until ?? ""} onChange={(v) => setDraftFilters({ ...draftFilters, until: v || undefined })} />
                    </div>
                  )}
                  <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
                    <span className="text-[12px] text-ink-faint">
                      {activeFilterCount > 0
                        ? `${activeFilterCount} filter${activeFilterCount === 1 ? "" : "s"} active`
                        : "No filters applied"}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setAdvancedOpen(!advancedOpen)}
                        className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink-muted hover:text-ink"
                      >
                        {advancedOpen ? "Fewer filters" : "More filters"}
                        <ChevronDown className={`h-3 w-3 transition-transform ${advancedOpen ? "rotate-180" : ""}`} />
                      </button>
                      <button
                        onClick={() => { setDraftFilters({}); setAppliedFilters({}); }}
                        className="cursor-pointer rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink-muted hover:text-ink"
                      >
                        Reset
                      </button>
                      <Button size="sm" onClick={() => setAppliedFilters({ ...draftFilters })}>
                        Apply filters
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* Failure-cluster banner */}
              {failureCluster && dismissedCluster !== clusterKey && (
                <WarningBanner
                  tone="warning"
                  className="mt-4"
                  action={
                    <span className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          const next = { ...appliedFilters, status: "failed" };
                          setAppliedFilters(next);
                          setDraftFilters(next);
                        }}
                        className="cursor-pointer whitespace-nowrap text-[13px] font-medium text-warning underline-offset-2 hover:underline"
                      >
                        Show these →
                      </button>
                      <button
                        type="button"
                        onClick={() => setDismissedCluster(clusterKey)}
                        className="cursor-pointer rounded-full p-1 text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
                        title="Dismiss"
                        aria-label="Dismiss failure-cluster banner"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  }
                >
                  <span className="font-semibold text-ink">
                    {failureCluster.length} {failureCluster[0].trigger} runs failed on{" "}
                    {new Date(failureCluster[0].started_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </span>
                  , {formatClock(failureCluster[0].started_at)}–
                  {formatClock(failureCluster[failureCluster.length - 1].started_at)}, each in under{" "}
                  {fmtLatency(Math.max(...failureCluster.map((r) => r.latency_ms)))} — likely a
                  configuration problem, not a model error.
                </WarningBanner>
              )}

              {runsError && <p className="mt-3 text-[13px] text-danger">{runsError}</p>}

              {/* Runs table */}
              <div className="mt-4 overflow-hidden rounded-lg border border-line bg-surface">
                {loadingRuns ? (
                  <p className="py-10 text-center text-[13px] text-ink-faint">Loading…</p>
                ) : runs.length === 0 ? (
                  <p className="py-10 text-center text-[13px] text-ink-faint">No runs match</p>
                ) : (
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="border-b border-line text-left text-[12px] text-ink-muted">
                        <th className="px-4 py-2.5 font-medium">Status</th>
                        <th className="px-4 py-2.5 font-medium">Trigger</th>
                        <th className="px-4 py-2.5 text-right font-medium">Tokens</th>
                        <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                        <th className="px-4 py-2.5 font-medium">Duration</th>
                        <th className="px-4 py-2.5 text-right font-medium">Started</th>
                        <th className="w-8 px-2 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {runs.map((r) => {
                        const st = RUN_STATUS[r.status] ?? {
                          kind: "idle" as StatusKind,
                          label: r.status.charAt(0).toUpperCase() + r.status.slice(1),
                        };
                        const failed = r.status === "failed";
                        return (
                          <tr
                            key={r.id}
                            onClick={() => navigate(`/traces/${r.agent_id}/${r.id}`)}
                            className={`cursor-pointer transition-colors ${
                              failed ? "bg-danger-tint hover:bg-danger-tint" : "hover:bg-sunken/60"
                            }`}
                          >
                            <td className="px-4 py-2.5">
                              <StatusWord status={st.kind} label={st.label} />
                            </td>
                            <td className="px-4 py-2.5">
                              <span className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                                {r.trigger}
                              </span>
                              {failed && r.error && (
                                <p className="mt-1 max-w-[280px] truncate font-mono text-[11px] text-danger" title={r.error}>
                                  [{r.error}]
                                </p>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-[12px] tabular-nums text-ink">
                              {(r.tokens_in + r.tokens_out).toLocaleString()}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-[12px] tabular-nums text-ink-muted">
                              {fmtCost(r.cost)}
                            </td>
                            <td className="px-4 py-2.5">
                              <span className="flex items-center gap-2">
                                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-track">
                                  <span
                                    className={`block h-full rounded-full ${failed ? "bg-danger" : "bg-accent"}`}
                                    style={{ width: `${Math.max(3, (r.latency_ms / maxLatency) * 100)}%` }}
                                  />
                                </span>
                                <span className="whitespace-nowrap text-[12px] tabular-nums text-ink-muted">
                                  {fmtLatency(r.latency_ms)}
                                </span>
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-right text-[12px] text-ink-muted">
                              {fmtStarted(r.started_at)}
                            </td>
                            <td className="px-2 py-2.5">
                              <ChevronRight className="h-3.5 w-3.5 text-ink-faint" />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>

              {hasMore && (
                <div className="mt-3 flex justify-center">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={loadingMore}
                    onClick={() => void fetchRuns(runs.length, true)}
                  >
                    {loadingMore ? "Loading…" : `Load more — showing ${runs.length}`}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** "{n} {name}s" for the dominant capability in a run's audit records. */
function topCapability(records: RunDetail["audit_records"]): string {
  if (records.length === 0) return "none";
  const counts = new Map<string, number>();
  for (const r of records) counts.set(r.capability_name, (counts.get(r.capability_name) ?? 0) + 1);
  const [name, n] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  const short = name.replace(/^web_/, "").replace(/_/g, " ");
  return `${n} ${short}${n === 1 ? "" : "s"}`;
}

// --- Run Trace View (Langfuse-style) ---

function RunTraceView({
  run,
  providerNames,
  egressCaps,
  view,
  onViewChange,
  ctxRef,
}: {
  run: RunDetail;
  providerNames: Record<string, string>;
  egressCaps: Set<string>;
  view: "timeline" | "messages";
  onViewChange: (v: "timeline" | "messages") => void;
  ctxRef: React.RefObject<HTMLDetailsElement | null>;
}) {
  const [subTab, setSubTab] = useState<"trace" | "syscalls">("trace");

  // Shared tab pills — each sub-view renders them on its own toolbar row so
  // its controls sit on the same line.
  const tabsRow = (
    <FilterPills
      variant="segmented"
      pills={[
        { key: "timeline", label: "Timeline" },
        { key: "messages", label: "Messages" },
        { key: "syscalls", label: "Syscalls", count: run.audit_records.length },
      ]}
      active={subTab === "syscalls" ? "syscalls" : view}
      onChange={(k) => {
        if (k === "syscalls") setSubTab("syscalls");
        else {
          setSubTab("trace");
          onViewChange(k as "timeline" | "messages");
        }
      }}
    />
  );

  return (
    <div>
      {run.error && (
        <WarningBanner tone="danger" className="mb-4" title="Run failed">
          <span className="break-all font-mono text-[12px]">{run.error}</span>
        </WarningBanner>
      )}
      {(run.manifest || run.context_tokens > 0 || run.loaded_capabilities.length > 0) && (
        <details ref={ctxRef} className="mb-4 rounded-md border border-line bg-surface px-4 py-3">
          <summary className="cursor-pointer select-none text-[12px] font-medium text-ink-muted">
            Context &amp; pinned configuration
          </summary>
          {(run.context_tokens > 0 || run.loaded_capabilities.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-muted">
              <span>Context: {run.context_tokens.toLocaleString()}{run.max_context_tokens > 0 ? ` / ${run.max_context_tokens.toLocaleString()}` : ""}</span>
              <span>Tool schemas: {run.context_breakdown.tools.toLocaleString()} tokens</span>
              <span>{run.loaded_capabilities.length} loaded on demand</span>
              {run.loaded_capabilities.length > 0 && (
                <span className="font-mono text-ink-faint" title={run.loaded_capabilities.join(", ")}>
                  {run.loaded_capabilities.join(", ")}
                </span>
              )}
            </div>
          )}
          {run.manifest && (
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-ink-muted md:grid-cols-3">
            <span>Agent v{run.manifest.agent_version_number ?? "?"} ({(run.manifest.agent_version_id ?? "").slice(0, 8)})</span>
            <span>Model: {run.manifest.model_provider_id}/{run.manifest.model_name}</span>
            <span className="break-all">Schedule: {(run.manifest.schedule_revision_id ?? "—").slice(0, 12)}</span>
            <span>Retrieval profile: {(run.manifest.retrieval_profile_revision_id ?? "—").slice(0, 12)}</span>
            <span>Browser profile: {(run.manifest.browser_profile_id ?? "—").slice(0, 12)}</span>
            <span className="col-span-2 md:col-span-3">
              Skills:{" "}
              {Array.isArray(run.manifest.skill_revision_ids)
                ? (run.manifest.skill_revision_ids.length
                    ? run.manifest.skill_revision_ids.join(", ")
                    : "—")
                : Object.entries(run.manifest.skill_revision_ids)
                    .map(([n, r]) => `${n}@${String(r).slice(0, 8)}`)
                    .join(", ") || "—"}
            </span>
            <span className="col-span-2 md:col-span-3">
              Knowledge snapshots: {(run.manifest.knowledge_snapshot_ids ?? []).length} ·
              Artifact bases: {(run.manifest.artifact_base_revision_ids ?? []).length}
            </span>
          </div>
          )}
          <p className="mt-1 text-[10px] text-ink-faint">
            Snapshot references only — ids link to stored revisions, not live objects.
          </p>
        </details>
      )}

      {/* Trace view */}
      {subTab === "trace" && (
        <>
          {view === "timeline" && (
            <>
              <div className="mb-4">{tabsRow}</div>
              <RunTimeline
                key={run.id}
                events={run.timeline ?? []}
                run={run}
                providerNames={providerNames}
                onViewMessages={() => onViewChange("messages")}
              />
            </>
          )}
          {view === "messages" && <RunMessages run={run} tabs={tabsRow} />}
        </>
      )}

      {subTab === "syscalls" && (
        <RunSyscalls run={run} egress={egressCaps} tabs={tabsRow} />
      )}
    </div>
  );
}

function FilterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-ink-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-8 w-full rounded-md border border-line bg-ground px-2.5 text-[12px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
      />
    </label>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { key: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-ink-muted">{label}</span>
      <Select
        value={value}
        onChange={onChange}
        options={[
          { value: "", label: "All" },
          ...options.map((o) => ({ value: o.key, label: o.label })),
        ]}
        className="h-8 w-full cursor-pointer rounded-md border border-line bg-ground px-2 text-[12px] text-ink outline-none transition-colors focus:border-accent"
        align="left" panelClassName="text-[12px]"
      />
    </label>
  );
}

const STATUS_OPTIONS = Object.entries(RUN_STATUS).map(([key, v]) => ({ key, label: v.label }));

const DATE_OPTIONS = [
  { key: "today", label: "Today" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
];

/** Dropdown chip for quick one-tap filters — applies immediately, clears via ×. */
function QuickFilterChip({
  label,
  active,
  activeKey,
  options,
  onPick,
}: {
  label: string;
  active?: string;
  activeKey?: string;
  options: { key: string; label: string }[];
  onPick: (key: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const hl = activeKey ?? active;
  return (
    <div className="relative">
      <span
        className={`inline-flex items-center rounded-full text-[13px] font-medium ${
          active
            ? "bg-accent-tint text-accent"
            : "border border-line bg-surface text-ink-muted hover:text-ink"
        }`}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex cursor-pointer items-center gap-1 px-3 py-1.5"
        >
          {active ? `${label}: ${active}` : label}
          <ChevronDown className="h-3 w-3" />
        </button>
        {active && (
          <button
            type="button"
            onClick={() => onPick(null)}
            className="mr-1.5 cursor-pointer rounded-full p-0.5 hover:bg-accent/20"
            title={`Clear ${label.toLowerCase()} filter`}
            aria-label={`Clear ${label} filter`}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </span>
      {open && (
        <>
          <div className="fixed inset-0 z-10 cursor-default" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 min-w-[170px] rounded-md border border-line bg-surface py-1 shadow-lg">
            {options.length === 0 ? (
              <p className="px-3 py-1.5 text-[12px] text-ink-faint">No options yet</p>
            ) : (
              options.map((o) => (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => {
                    onPick(o.key);
                    setOpen(false);
                  }}
                  className={`block w-full cursor-pointer px-3 py-1.5 text-left text-[12px] transition-colors hover:bg-sunken ${
                    hl === o.key ? "font-medium text-accent" : "text-ink"
                  }`}
                >
                  {o.label}
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
