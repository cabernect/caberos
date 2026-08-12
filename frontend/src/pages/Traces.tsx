import { useState, useEffect, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { GitBranch, ChevronRight, ArrowLeft, Clock, DollarSign, AlertCircle, Layers, MessageSquare, Shield } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import type { Agent, RunSummary, RunDetail, AuditOut, AgentStat, DashboardStats } from "@/lib/types";

export function Traces() {
  const { agentId, runId } = useParams();
  const navigate = useNavigate();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);

  // Agent list state
  const [agentStats, setAgentStats] = useState<AgentStat[]>([]);

  // Agent runs state
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // Run detail state
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [detailView, setDetailView] = useState<"timeline" | "messages">("timeline");

  const fetchAgents = useCallback(async () => {
    try {
      setAgents(await api.listAgents());
    } catch {}
  }, []);

  const fetchAgentStats = useCallback(async () => {
    try {
      const data = await api.getDashboardStats(30);
      setAgentStats(data.by_agent);
    } catch {}
  }, []);

  const fetchRuns = useCallback(async () => {
    if (!agentId) return;
    setLoadingRuns(true);
    try {
      const data = await api.listRuns({ agent_id: agentId, is_test: false, limit: 100 });
      setRuns(data);
    } catch {
      setRuns([]);
    } finally {
      setLoadingRuns(false);
    }
  }, [agentId]);

  const fetchRunDetail = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await api.getRunDetail(runId);
      setRunDetail(data);
    } catch {
      setRunDetail(null);
    }
  }, [runId]);

  useEffect(() => {
    fetchAgents();
    fetchAgentStats();
  }, [fetchAgents, fetchAgentStats]);

  useEffect(() => {
    if (agentId) fetchRuns();
  }, [agentId, fetchRuns]);

  useEffect(() => {
    if (runId) fetchRunDetail();
  }, [runId, fetchRunDetail]);

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
  const fmtDate = (d: string) => new Date(d).toLocaleString();
  const fmtLatency = (ms: number) => (ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);
  const statusColor = (s: string) => {
    if (s === "completed") return "#22c55e";
    if (s === "failed") return "#ef4444";
    if (s === "running") return "#3b82f6";
    return "var(--ink-3)";
  };

  const activeAgent = agentId ? agents.find((a) => a.id === agentId) : null;

  // Determine which view to render
  const view: "agentList" | "agentRuns" | "runDetail" = runId ? "runDetail" : agentId ? "agentRuns" : "agentList";

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="traces"
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
            <GitBranch className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <h1 className="text-[18px] font-semibold text-[var(--ink)]">Traces</h1>
            {view === "agentRuns" && activeAgent && (
              <>
                <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />
                <span className="text-[15px] text-[var(--ink-2)]">{activeAgent.name}</span>
              </>
            )}
            {view === "runDetail" && runDetail && (
              <>
                <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />
                <button
                  onClick={() => navigate(`/traces/${agentId}`)}
                  className="text-[15px] text-[var(--ink-2)]"
                  style={{ background: "none", border: "none", cursor: "pointer" }}
                >
                  {runDetail.agent_name || agentName(runDetail.agent_id)}
                </button>
                <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />
                <span className="text-[15px] font-mono text-[var(--ink-2)]">{runDetail.id.slice(0, 8)}</span>
              </>
            )}
          </div>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
            {view === "agentList" && "Select an agent to view its traces"}
            {view === "agentRuns" && "Runs for this agent — click any run for full trace detail"}
            {view === "runDetail" && "Run trace detail"}
          </p>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-6xl">
            {/* --- Agent List View --- */}
            {view === "agentList" && (
              <div className="grid grid-cols-3 gap-4">
                {agents.length === 0 ? (
                  <p className="col-span-3 py-8 text-center text-[13px] text-[var(--ink-3)]">No agents found</p>
                ) : (
                  agents.map((a) => {
                    const stat = agentStats.find((s) => s.agent_id === a.id);
                    return (
                      <div
                        key={a.id}
                        onClick={() => navigate(`/traces/${a.id}`)}
                        className="cursor-pointer rounded-[8px] border p-4 transition hover:border-[var(--accent)]"
                        style={{ borderColor: "var(--border)", background: "var(--white)" }}
                      >
                        <div className="flex items-center justify-between">
                          <h3 className="text-[15px] font-semibold text-[var(--ink)]">{a.name}</h3>
                          <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />
                        </div>
                        <div className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
                          <div>
                            <p className="text-[10px] uppercase text-[var(--ink-3)]">Runs</p>
                            <p className="font-semibold text-[var(--ink)]">{stat?.run_count ?? 0}</p>
                          </div>
                          <div>
                            <p className="text-[10px] uppercase text-[var(--ink-3)]">Cost</p>
                            <p className="font-semibold text-[var(--ink)]">{stat ? fmtCost(stat.total_cost) : "$0"}</p>
                          </div>
                          <div>
                            <p className="text-[10px] uppercase text-[var(--ink-3)]">Errors</p>
                            <p className="font-semibold" style={{ color: (stat?.error_count ?? 0) > 0 ? "#ef4444" : "var(--ink)" }}>
                              {stat?.error_count ?? 0}
                            </p>
                          </div>
                        </div>
                        {stat?.last_active && (
                          <p className="mt-2 text-[11px] text-[var(--ink-3)]">
                            Last active: {fmtDate(stat.last_active)}
                          </p>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            )}

            {/* --- Agent Runs View --- */}
            {view === "agentRuns" && (
              <div>
                {/* Agent info header */}
                {activeAgent && (
                  <div className="mb-4 rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                    <h2 className="text-[16px] font-semibold text-[var(--ink)]">{activeAgent.name}</h2>
                    <div className="mt-2 flex gap-6 text-[12px] text-[var(--ink-2)]">
                      <span>ID: <span className="font-mono">{activeAgent.id.slice(0, 8)}</span></span>
                      <span>Enabled: {activeAgent.enabled ? "yes" : "no"}</span>
                      <span>{runs.length} runs</span>
                    </div>
                  </div>
                )}

                {/* Runs table */}
                {loadingRuns ? (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading...</p>
                ) : runs.length === 0 ? (
                  <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No runs for this agent</p>
                ) : (
                  <div className="overflow-x-auto rounded-[8px] border" style={{ borderColor: "var(--border)" }}>
                    <table className="w-full text-[12px]">
                      <thead style={{ background: "var(--surface)" }}>
                        <tr style={{ borderBottom: "1px solid var(--border)" }}>
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
                            onClick={() => navigate(`/traces/${r.agent_id}/${r.id}`)}
                          >
                            <td className="px-3 py-2">
                              <div className="flex items-center gap-1.5">
                                <div className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor(r.status) }} />
                                <span style={{ color: statusColor(r.status), fontWeight: 500 }}>{r.status}</span>
                              </div>
                            </td>
                            <td className="px-3 py-2 text-[var(--ink-2)]">{r.trigger}</td>
                            <td className="px-3 py-2 text-right text-[var(--ink-2)]">{fmtCost(r.cost)}</td>
                            <td className="px-3 py-2 text-right text-[var(--ink-2)]">{r.tokens_in + r.tokens_out}</td>
                            <td className="px-3 py-2 text-right text-[var(--ink-2)]">{fmtLatency(r.latency_ms)}</td>
                            <td className="px-3 py-2 text-[var(--ink-3)]">{fmtDate(r.started_at)}</td>
                            <td className="px-3 py-2"><ChevronRight className="h-3.5 w-3.5 text-[var(--ink-3)]" /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* --- Run Detail View --- */}
            {view === "runDetail" && runDetail && (
              <RunTraceView
                run={runDetail}
                agentName={runDetail.agent_name || agentName(runDetail.agent_id)}
                fmtCost={fmtCost}
                fmtDate={fmtDate}
                fmtLatency={fmtLatency}
                statusColor={statusColor}
                view={detailView}
                onViewChange={setDetailView}
                onBack={() => navigate(`/traces/${agentId}`)}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Run Trace View (Langfuse-style) ---

function RunTraceView({
  run,
  agentName,
  fmtCost,
  fmtDate,
  fmtLatency,
  statusColor,
  view,
  onViewChange,
  onBack,
}: {
  run: RunDetail;
  agentName: string;
  fmtCost: (c: number) => string;
  fmtDate: (d: string) => string;
  fmtLatency: (ms: number) => string;
  statusColor: (s: string) => string;
  view: "timeline" | "messages";
  onViewChange: (v: "timeline" | "messages") => void;
  onBack: () => void;
}) {
  const [subTab, setSubTab] = useState<"trace" | "syscalls">("trace");

  return (
    <div>
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1 text-[13px] text-[var(--ink-2)]"
        style={{ background: "none", border: "none", cursor: "pointer" }}
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to runs
      </button>

      {/* Run header */}
      <div className="mb-4 rounded-[8px] border p-4" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-[16px] font-semibold text-[var(--ink)]">
              {run.id.slice(0, 8)} · {agentName}
            </h3>
            <p className="mt-1 text-[12px] text-[var(--ink-2)]">
              <span style={{ color: statusColor(run.status), fontWeight: 500 }}>{run.status}</span>
              {" · "}
              {run.trigger} · {fmtDate(run.started_at)}
            </p>
          </div>
          <div className="grid grid-cols-4 gap-4 text-right text-[12px]">
            <div>
              <p className="text-[10px] uppercase text-[var(--ink-3)]">Cost</p>
              <p className="font-semibold text-[var(--ink)]">{fmtCost(run.cost)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-[var(--ink-3)]">Tokens</p>
              <p className="font-semibold text-[var(--ink)]">{run.tokens_in + run.tokens_out}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-[var(--ink-3)]">In/Out</p>
              <p className="font-semibold text-[var(--ink)]">{run.tokens_in}/{run.tokens_out}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-[var(--ink-3)]">Latency</p>
              <p className="font-semibold text-[var(--ink)]">{fmtLatency(run.latency_ms)}</p>
            </div>
          </div>
        </div>
        {run.error && (
          <div className="mt-3 flex items-start gap-2 rounded-[4px] p-2" style={{ background: "rgba(239,68,68,0.08)" }}>
            <AlertCircle className="h-4 w-4 flex-shrink-0" style={{ color: "#ef4444" }} />
            <p className="text-[12px]" style={{ color: "#ef4444" }}>{run.error}</p>
          </div>
        )}
      </div>

      {/* Sub-tabs: Trace | Syscalls */}
      <div className="mb-4 flex gap-1" style={{ borderBottom: "1px solid var(--border)" }}>
        <SubTab active={subTab === "trace"} onClick={() => setSubTab("trace")} icon={Layers} label="Trace" />
        <SubTab active={subTab === "syscalls"} onClick={() => setSubTab("syscalls")} icon={Shield} label={`Syscalls (${run.audit_records.length})`} />
      </div>

      {/* Trace sub-tab */}
      {subTab === "trace" && (
        <>
          {/* View toggle */}
          <div className="mb-3 flex gap-1">
            <ViewToggle active={view === "timeline"} onClick={() => onViewChange("timeline")} icon={Clock} label="Timeline" />
            <ViewToggle active={view === "messages"} onClick={() => onViewChange("messages")} icon={MessageSquare} label="Messages" />
          </div>

          {/* Timeline view */}
          {view === "timeline" && (
            <div className="space-y-1">
              {run.messages.map((m, i) => {
                const isTool = m.role === "tool" || m.role === "tool_call";
                const isThinking = m.role === "thinking";
                const isUser = m.role === "user";
                const isAssistant = m.role === "assistant";
                const indent = isTool ? 32 : isThinking ? 16 : 0;
                const color = isUser ? "#3b82f6" : isAssistant ? "#22c55e" : isThinking ? "#a855f7" : "#f59e0b";
                const label = isUser ? "user" : isAssistant ? "assistant" : isThinking ? "thinking" : isTool ? "tool" : m.role;

                return (
                  <div key={m.id} className="relative">
                    {/* Vertical line */}
                    {i < run.messages.length - 1 && (
                      <div
                        className="absolute top-6 bottom-0 w-px"
                        style={{ left: 12 + indent, background: "var(--border)" }}
                      />
                    )}
                    <div
                      className="relative flex items-start gap-3 rounded-[6px] border p-3"
                      style={{
                        borderColor: "var(--border)",
                        background: "var(--white)",
                        marginLeft: indent,
                      }}
                    >
                      {/* Dot */}
                      <div className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full" style={{ background: color }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className="rounded-[3px] px-1.5 py-0.5 text-[10px] font-medium"
                            style={{ background: color, color: "white" }}
                          >
                            {label}
                          </span>
                          <span className="text-[10px] text-[var(--ink-3)]">{fmtDate(m.created_at)}</span>
                          {m.subagent_id && (
                            <span className="text-[10px] text-[var(--ink-3)]">sub: {m.subagent_id.slice(0, 8)}</span>
                          )}
                        </div>
                        <p className="mt-1.5 whitespace-pre-wrap break-words text-[12px] text-[var(--ink)]">
                          {m.content.length > 1000 ? m.content.slice(0, 1000) + "..." : m.content}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Messages view */}
          {view === "messages" && (
            <div className="space-y-2">
              {run.messages.map((m) => (
                <div key={m.id} className="rounded-[6px] border p-3" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
                  <div className="flex items-center gap-2">
                    <span
                      className="rounded-[3px] px-1.5 py-0.5 text-[10px] font-medium"
                      style={{
                        background: m.role === "user" ? "#3b82f6" : m.role === "assistant" ? "#22c55e" : m.role === "thinking" ? "#a855f7" : "var(--border)",
                        color: m.role === "user" || m.role === "assistant" || m.role === "thinking" ? "white" : "var(--ink-2)",
                      }}
                    >
                      {m.role}
                    </span>
                    <span className="text-[10px] text-[var(--ink-3)]">{fmtDate(m.created_at)}</span>
                  </div>
                  <p className="mt-1.5 whitespace-pre-wrap text-[12px] text-[var(--ink)]">{m.content}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Syscalls sub-tab */}
      {subTab === "syscalls" && (
        <div>
          {run.audit_records.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No syscalls in this run</p>
          ) : (
            <div className="space-y-2">
              {run.audit_records.map((a) => (
                <div
                  key={a.id}
                  className="rounded-[6px] border p-3"
                  style={{
                    borderColor: a.allowed ? "var(--border)" : "#ef4444",
                    background: a.allowed ? "var(--white)" : "rgba(239,68,68,0.04)",
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[12px] font-medium text-[var(--ink)]">{a.capability_name}</span>
                    <span className="text-[11px] font-medium" style={{ color: a.allowed ? "#22c55e" : "#ef4444" }}>
                      {a.allowed ? "allowed" : "DENIED"}
                    </span>
                  </div>
                  {a.denied_reason && (
                    <p className="mt-1 text-[11px]" style={{ color: "#ef4444" }}>Reason: {a.denied_reason}</p>
                  )}
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <div>
                      <p className="text-[10px] uppercase text-[var(--ink-3)]">Args</p>
                      <p className="mt-0.5 font-mono text-[10px] text-[var(--ink-2)] break-all">
                        {a.args.slice(0, 300)}{a.args.length > 300 ? "..." : ""}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase text-[var(--ink-3)]">Result</p>
                      <p className="mt-0.5 font-mono text-[10px] text-[var(--ink-2)] break-all">
                        {a.result ? (a.result.slice(0, 300) + (a.result.length > 300 ? "..." : "")) : "—"}
                      </p>
                    </div>
                  </div>
                  <div className="mt-2 flex gap-4 text-[10px] text-[var(--ink-3)]">
                    <span>Cost: {a.cost > 0 ? fmtCost(a.cost) : "—"}</span>
                    <span>Latency: {a.latency_ms > 0 ? fmtLatency(a.latency_ms) : "—"}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SubTab({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: typeof Layers; label: string }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition"
      style={{
        color: active ? "var(--accent)" : "var(--ink-2)",
        borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
        background: "none",
        cursor: "pointer",
      }}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function ViewToggle({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: typeof Clock; label: string }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-[4px] px-2.5 py-1.5 text-[12px] font-medium transition"
      style={{
        background: active ? "var(--accent)" : "var(--surface)",
        color: active ? "white" : "var(--ink-2)",
        border: "1px solid var(--border)",
        cursor: "pointer",
      }}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}
