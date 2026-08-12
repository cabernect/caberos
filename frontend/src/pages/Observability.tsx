import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, ChevronRight, DollarSign, Shield, AlertCircle, Clock, Cpu } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import type { RunSummary, RunDetail, AuditOut, SpendSummary, HealthStatus, Agent } from "@/lib/types";

type Tab = "runs" | "audit" | "spend" | "health";

export function Observability() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [tab, setTab] = useState<Tab>("runs");
  const [agents, setAgents] = useState<Agent[]>([]);
  const navigate = useNavigate();

  // Runs state
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runFilterAgent, setRunFilterAgent] = useState("");
  const [runFilterStatus, setRunFilterStatus] = useState("");
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // Audit state
  const [auditRecords, setAuditRecords] = useState<AuditOut[]>([]);
  const [auditFilterAgent, setAuditFilterAgent] = useState("");
  const [auditFilterAllowed, setAuditFilterAllowed] = useState("");
  const [loadingAudit, setLoadingAudit] = useState(false);

  // Spend state
  const [spend, setSpend] = useState<SpendSummary | null>(null);
  const [spendDays, setSpendDays] = useState(1);

  // Health state
  const [health, setHealth] = useState<HealthStatus | null>(null);

  const fetchAgents = useCallback(async () => {
    try {
      const ags = await api.listAgents();
      setAgents(ags);
    } catch {}
  }, []);

  const fetchRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const data = await api.listRuns({
        agent_id: runFilterAgent || undefined,
        status: runFilterStatus || undefined,
        is_test: false,
        limit: 100,
      });
      setRuns(data);
    } catch {
      setRuns([]);
    } finally {
      setLoadingRuns(false);
    }
  }, [runFilterAgent, runFilterStatus]);

  const fetchAudit = useCallback(async () => {
    setLoadingAudit(true);
    try {
      const data = await api.listAudit({
        agent_id: auditFilterAgent || undefined,
        allowed: auditFilterAllowed === "" ? undefined : auditFilterAllowed === "true",
        limit: 100,
      });
      setAuditRecords(data);
    } catch {
      setAuditRecords([]);
    } finally {
      setLoadingAudit(false);
    }
  }, [auditFilterAgent, auditFilterAllowed]);

  const fetchSpend = useCallback(async () => {
    try {
      const data = await api.getSpend(spendDays);
      setSpend(data);
    } catch {
      setSpend(null);
    }
  }, [spendDays]);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await api.getHealth();
      setHealth(data);
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    if (tab === "runs") fetchRuns();
    if (tab === "audit") fetchAudit();
    if (tab === "spend") fetchSpend();
    if (tab === "health") fetchHealth();
  }, [tab, fetchRuns, fetchAudit, fetchSpend, fetchHealth]);

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
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
    if (page === "observability") return;
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  const fmtCost = (c: number) => `$${c.toFixed(4)}`;
  const fmtDate = (d: string) => new Date(d).toLocaleString();
  const fmtLatency = (ms: number) => (ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

  const statusColor = (s: string) => {
    if (s === "completed") return "var(--green, #22c55e)";
    if (s === "failed") return "var(--red, #ef4444)";
    if (s === "running") return "var(--blue, #3b82f6)";
    return "var(--ink-3)";
  };

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
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <h1 className="text-[18px] font-semibold text-[var(--ink)]">Observability</h1>
          </div>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
            Audit every action — runs, syscalls, spend, and system health
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-8 pt-4" style={{ borderBottom: "1px solid var(--border)" }}>
          {([
            { key: "runs", label: "Runs", icon: Clock },
            { key: "audit", label: "Syscall Log", icon: Shield },
            { key: "spend", label: "Spend", icon: DollarSign },
            { key: "health", label: "Health", icon: Cpu },
          ] as { key: Tab; label: string; icon: typeof Clock }[]).map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className="flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition"
                style={{
                  color: tab === t.key ? "var(--accent)" : "var(--ink-2)",
                  borderBottom: tab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
                  background: "none",
                  cursor: "pointer",
                }}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-5xl">
            {/* Runs tab */}
            {tab === "runs" && (
              <div>
                {/* Run detail modal */}
                {selectedRun ? (
                  <RunDetailView
                    run={selectedRun}
                    agentName={agentName(selectedRun.agent_id)}
                    fmtCost={fmtCost}
                    fmtDate={fmtDate}
                    fmtLatency={fmtLatency}
                    statusColor={statusColor}
                    onBack={() => setSelectedRun(null)}
                  />
                ) : (
                  <>
                    {/* Filters */}
                    <div className="mb-4 flex gap-3">
                      <select
                        value={runFilterAgent}
                        onChange={(e) => setRunFilterAgent(e.target.value)}
                        className="rounded-[4px] border px-2 py-1.5 text-[13px]"
                        style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                      >
                        <option value="">All agents</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>{a.name}</option>
                        ))}
                      </select>
                      <select
                        value={runFilterStatus}
                        onChange={(e) => setRunFilterStatus(e.target.value)}
                        className="rounded-[4px] border px-2 py-1.5 text-[13px]"
                        style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                      >
                        <option value="">All statuses</option>
                        <option value="completed">Completed</option>
                        <option value="failed">Failed</option>
                        <option value="running">Running</option>
                      </select>
                      <button
                        onClick={fetchRuns}
                        className="rounded-[4px] border px-3 py-1.5 text-[13px]"
                        style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
                      >
                        Refresh
                      </button>
                    </div>

                    {/* Runs table */}
                    {loadingRuns ? (
                      <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading...</p>
                    ) : runs.length === 0 ? (
                      <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No runs found</p>
                    ) : (
                      <div className="overflow-x-auto rounded-[8px] border" style={{ borderColor: "var(--border)" }}>
                        <table className="w-full text-[12px]">
                          <thead style={{ background: "var(--surface)" }}>
                            <tr style={{ borderBottom: "1px solid var(--border)" }}>
                              <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Agent</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Status</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Trigger</th>
                              <th className="px-3 py-2 text-right font-medium text-[var(--ink-2)]">Cost</th>
                              <th className="px-3 py-2 text-right font-medium text-[var(--ink-2)]">Tokens</th>
                              <th className="px-3 py-2 text-right font-medium text-[var(--ink-2)]">Latency</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Started</th>
                              <th className="px-3 py-2"></th>
                            </tr>
                          </thead>
                          <tbody>
                            {runs.map((r) => (
                              <tr
                                key={r.id}
                                className="cursor-pointer transition hover:bg-[var(--surface)]"
                                style={{ borderBottom: "1px solid var(--border)" }}
                                onClick={async () => {
                                  try {
                                    const detail = await api.getRunDetail(r.id);
                                    setSelectedRun(detail);
                                  } catch {}
                                }}
                              >
                                <td className="px-3 py-2 text-[var(--ink)]">{r.agent_name || agentName(r.agent_id)}</td>
                                <td className="px-3 py-2">
                                  <span style={{ color: statusColor(r.status), fontWeight: 500 }}>{r.status}</span>
                                </td>
                                <td className="px-3 py-2 text-[var(--ink-2)]">{r.trigger}</td>
                                <td className="px-3 py-2 text-right text-[var(--ink-2)]">{fmtCost(r.cost)}</td>
                                <td className="px-3 py-2 text-right text-[var(--ink-2)]">
                                  {r.tokens_in + r.tokens_out}
                                </td>
                                <td className="px-3 py-2 text-right text-[var(--ink-2)]">{fmtLatency(r.latency_ms)}</td>
                                <td className="px-3 py-2 text-[var(--ink-3)]">{fmtDate(r.started_at)}</td>
                                <td className="px-3 py-2">
                                  <ChevronRight className="h-3.5 w-3.5 text-[var(--ink-3)]" />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Audit tab */}
            {tab === "audit" && (
              <div>
                <div className="mb-4 flex gap-3">
                  <select
                    value={auditFilterAgent}
                    onChange={(e) => setAuditFilterAgent(e.target.value)}
                    className="rounded-[4px] border px-2 py-1.5 text-[13px]"
                    style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                  >
                    <option value="">All agents</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                  <select
                    value={auditFilterAllowed}
                    onChange={(e) => setAuditFilterAllowed(e.target.value)}
                    className="rounded-[4px] border px-2 py-1.5 text-[13px]"
                    style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                  >
                    <option value="">All outcomes</option>
                    <option value="true">Allowed</option>
                    <option value="false">Denied</option>
                  </select>
                  <button
                    onClick={fetchAudit}
                    className="rounded-[4px] border px-3 py-1.5 text-[13px]"
                    style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
                  >
                    Refresh
                  </button>
                </div>

                {loadingAudit ? (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading...</p>
                ) : auditRecords.length === 0 ? (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No syscall records found</p>
                ) : (
                  <div className="overflow-x-auto rounded-[8px] border" style={{ borderColor: "var(--border)" }}>
                    <table className="w-full text-[12px]">
                      <thead style={{ background: "var(--surface)" }}>
                        <tr style={{ borderBottom: "1px solid var(--border)" }}>
                          <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Capability</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Agent</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Outcome</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Reason</th>
                          <th className="px-3 py-2 text-right font-medium text-[var(--ink-2)]">Cost</th>
                          <th className="px-3 py-2 text-right font-medium text-[var(--ink-2)]">Latency</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--ink-2)]">Run</th>
                        </tr>
                      </thead>
                      <tbody>
                        {auditRecords.map((a) => (
                          <tr key={a.id} style={{ borderBottom: "1px solid var(--border)" }}>
                            <td className="px-3 py-2 font-mono text-[var(--ink)]">{a.capability_name}</td>
                            <td className="px-3 py-2 text-[var(--ink-2)]">{agentName(a.agent_id)}</td>
                            <td className="px-3 py-2">
                              {a.allowed ? (
                                <span style={{ color: "var(--green, #22c55e)" }}>allowed</span>
                              ) : (
                                <span style={{ color: "var(--red, #ef4444)", fontWeight: 500 }}>DENIED</span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-[var(--ink-3)]">{a.denied_reason || "—"}</td>
                            <td className="px-3 py-2 text-right text-[var(--ink-2)]">{a.cost > 0 ? fmtCost(a.cost) : "—"}</td>
                            <td className="px-3 py-2 text-right text-[var(--ink-2)]">{a.latency_ms > 0 ? fmtLatency(a.latency_ms) : "—"}</td>
                            <td className="px-3 py-2 font-mono text-[var(--ink-3)]">{a.run_id.slice(0, 8)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Spend tab */}
            {tab === "spend" && (
              <div>
                <div className="mb-4 flex gap-3">
                  {[1, 7, 30].map((d) => (
                    <button
                      key={d}
                      onClick={() => setSpendDays(d)}
                      className="rounded-[4px] px-3 py-1.5 text-[13px] font-medium"
                      style={{
                        background: spendDays === d ? "var(--accent)" : "var(--surface)",
                        color: spendDays === d ? "white" : "var(--ink-2)",
                        border: "1px solid var(--border)",
        cursor: "pointer",
                      }}
                    >
                      {d === 1 ? "Today" : `${d} days`}
                    </button>
                  ))}
                </div>

                {spend ? (
                  <div className="space-y-4">
                    {/* Summary cards */}
                    <div className="grid grid-cols-3 gap-4">
                      <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                        <p className="text-[11px] text-[var(--ink-3)]">Total spend</p>
                        <p className="mt-1 text-[24px] font-semibold text-[var(--ink)]">{fmtCost(spend.total_cost)}</p>
                      </div>
                      <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                        <p className="text-[11px] text-[var(--ink-3)]">Total runs</p>
                        <p className="mt-1 text-[24px] font-semibold text-[var(--ink)]">{spend.total_runs}</p>
                      </div>
                      <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                        <p className="text-[11px] text-[var(--ink-3)]">Total tokens</p>
                        <p className="mt-1 text-[24px] font-semibold text-[var(--ink)]">
                          {(spend.total_tokens_in + spend.total_tokens_out).toLocaleString()}
                        </p>
                      </div>
                    </div>

                    {/* By agent */}
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <h3 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">By agent</h3>
                      {spend.by_agent.length === 0 ? (
                        <p className="text-[12px] text-[var(--ink-3)]">No spend data</p>
                      ) : (
                        <div className="space-y-2">
                          {spend.by_agent
                            .sort((a, b) => b.total_cost - a.total_cost)
                            .map((a) => {
                              const pct = spend.total_cost > 0 ? (a.total_cost / spend.total_cost) * 100 : 0;
                              return (
                                <div key={a.agent_id}>
                                  <div className="flex justify-between text-[12px]">
                                    <span className="text-[var(--ink)]">{a.agent_name || agentName(a.agent_id)}</span>
                                    <span className="text-[var(--ink-2)]">
                                      {fmtCost(a.total_cost)} · {a.run_count} runs
                                    </span>
                                  </div>
                                  <div className="mt-1 h-1.5 rounded-full" style={{ background: "var(--border)" }}>
                                    <div
                                      className="h-1.5 rounded-full"
                                      style={{ width: `${pct}%`, background: "var(--accent)" }}
                                    />
                                  </div>
                                </div>
                              );
                            })}
                        </div>
                      )}
                    </div>

                    {/* By trigger */}
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <h3 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">By trigger</h3>
                      {Object.keys(spend.by_trigger).length === 0 ? (
                        <p className="text-[12px] text-[var(--ink-3)]">No spend data</p>
                      ) : (
                        <div className="space-y-2">
                          {Object.entries(spend.by_trigger).map(([trigger, cost]) => (
                            <div key={trigger} className="flex justify-between text-[12px]">
                              <span className="text-[var(--ink)]">{trigger}</span>
                              <span className="text-[var(--ink-2)]">{fmtCost(cost)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading spend data...</p>
                )}
              </div>
            )}

            {/* Health tab */}
            {tab === "health" && (
              <div>
                {health ? (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-2 rounded-full" style={{ background: "var(--green, #22c55e)" }} />
                        <p className="text-[14px] font-semibold text-[var(--ink)]">System status</p>
                      </div>
                      <p className="mt-2 text-[24px] font-semibold" style={{ color: "var(--green, #22c55e)" }}>
                        {health.status.toUpperCase()}
                      </p>
                    </div>
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <p className="text-[14px] font-semibold text-[var(--ink)]">Database</p>
                      <p className="mt-2 text-[16px] text-[var(--ink-2)]">{health.database}</p>
                    </div>
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <p className="text-[14px] font-semibold text-[var(--ink)]">Agents</p>
                      <p className="mt-2 text-[24px] font-semibold text-[var(--ink)]">{health.agents}</p>
                    </div>
                    <div className="rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                      <p className="text-[14px] font-semibold text-[var(--ink)]">Active runs</p>
                      <p className="mt-2 text-[24px] font-semibold text-[var(--ink)]">{health.active_runs}</p>
                    </div>
                  </div>
                ) : (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading health...</p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Run detail view ---

function RunDetailView({
  run,
  agentName,
  fmtCost,
  fmtDate,
  fmtLatency,
  statusColor,
  onBack,
}: {
  run: RunDetail;
  agentName: string;
  fmtCost: (c: number) => string;
  fmtDate: (d: string) => string;
  fmtLatency: (ms: number) => string;
  statusColor: (s: string) => string;
  onBack: () => void;
}) {
  return (
    <div>
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1 text-[13px] text-[var(--ink-2)]"
        style={{ background: "none", border: "none", cursor: "pointer" }}
      >
        ← Back to runs
      </button>

      {/* Run header */}
      <div className="mb-4 rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[16px] font-semibold text-[var(--ink)]">
              Run {run.id.slice(0, 8)} · {agentName}
            </h3>
            <p className="mt-1 text-[12px] text-[var(--ink-2)]">
              {run.trigger} · <span style={{ color: statusColor(run.status) }}>{run.status}</span> · {fmtDate(run.started_at)}
            </p>
          </div>
          <div className="text-right text-[12px] text-[var(--ink-2)]">
            <p>Cost: {fmtCost(run.cost)}</p>
            <p>Tokens: {run.tokens_in + run.tokens_out} (in: {run.tokens_in}, out: {run.tokens_out})</p>
            <p>Latency: {fmtLatency(run.latency_ms)}</p>
          </div>
        </div>
        {run.error && (
          <div className="mt-3 flex items-start gap-2 rounded-[4px] p-2" style={{ background: "var(--red-bg, rgba(239,68,68,0.1))" }}>
            <AlertCircle className="h-4 w-4 flex-shrink-0" style={{ color: "var(--red, #ef4444)" }} />
            <p className="text-[12px]" style={{ color: "var(--red, #ef4444)" }}>{run.error}</p>
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="mb-4">
        <h4 className="mb-2 text-[13px] font-semibold text-[var(--ink)]">Messages ({run.messages.length})</h4>
        <div className="space-y-2">
          {run.messages.map((m) => (
            <div
              key={m.id}
              className="rounded-[6px] border p-3"
              style={{ borderColor: "var(--border)", background: "var(--white)" }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="rounded-[3px] px-1.5 py-0.5 text-[10px] font-medium"
                  style={{
                    background: m.role === "user" ? "var(--accent)" : m.role === "assistant" ? "var(--green, #22c55e)" : "var(--border)",
                    color: m.role === "user" || m.role === "assistant" ? "white" : "var(--ink-2)",
                  }}
                >
                  {m.role}
                </span>
                <span className="text-[11px] text-[var(--ink-3)]">{fmtDate(m.created_at)}</span>
                {m.subagent_id && (
                  <span className="text-[10px] text-[var(--ink-3)]">sub: {m.subagent_id.slice(0, 8)}</span>
                )}
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-[12px] text-[var(--ink)]">
                {m.content.length > 500 ? m.content.slice(0, 500) + "..." : m.content}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Audit records */}
      {run.audit_records.length > 0 && (
        <div>
          <h4 className="mb-2 text-[13px] font-semibold text-[var(--ink)]">
            Syscalls ({run.audit_records.length})
          </h4>
          <div className="space-y-2">
            {run.audit_records.map((a) => (
              <div
                key={a.id}
                className="rounded-[6px] border p-3"
                style={{
                  borderColor: a.allowed ? "var(--border)" : "var(--red, #ef4444)",
                  background: a.allowed ? "var(--white)" : "var(--red-bg, rgba(239,68,68,0.05))",
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[12px] font-medium text-[var(--ink)]">{a.capability_name}</span>
                  <span
                    className="text-[11px] font-medium"
                    style={{ color: a.allowed ? "var(--green, #22c55e)" : "var(--red, #ef4444)" }}
                  >
                    {a.allowed ? "allowed" : "DENIED"}
                  </span>
                </div>
                {a.denied_reason && (
                  <p className="mt-1 text-[11px]" style={{ color: "var(--red, #ef4444)" }}>Reason: {a.denied_reason}</p>
                )}
                <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                  Args: {a.args.slice(0, 200)}{a.args.length > 200 ? "..." : ""}
                </p>
                {a.result && (
                  <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">
                    Result: {a.result.slice(0, 200)}{a.result.length > 200 ? "..." : ""}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
