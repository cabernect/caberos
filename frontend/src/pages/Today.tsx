import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell,
  Bot,
  Check,
  CheckCircle2,
  Database,
  Loader2,
  MessageCircleQuestion,
  MonitorSmartphone,
  SendHorizonal,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { api, type HomeData, type NeedsYouItem } from "@/lib/api";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { ListRow } from "@/components/ui/list-row";
import { IconTile } from "@/components/ui/icon-tile";
import { EmptyState } from "@/components/ui/empty-state";
import { WarningBanner } from "@/components/ui/warning-banner";
import { CommandBar } from "@/components/ui/command-bar";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { formatClock } from "@/lib/time";

const KIND_META: Record<string, { icon: LucideIcon; tone: "warning" | "danger" | "sunken" }> = {
  approval_required: { icon: ShieldAlert, tone: "warning" },
  approval_timeout: { icon: ShieldAlert, tone: "danger" },
  elicitation_required: { icon: MessageCircleQuestion, tone: "warning" },
  browser_takeover_required: { icon: MonitorSmartphone, tone: "warning" },
  run_failed: { icon: XCircle, tone: "danger" },
  run_interrupted: { icon: XCircle, tone: "warning" },
  schedule_failed: { icon: XCircle, tone: "danger" },
  skill_publish_failed: { icon: Sparkles, tone: "danger" },
  memory_clarification: { icon: MessageCircleQuestion, tone: "warning" },
  memory_update_failed: { icon: XCircle, tone: "danger" },
  vault_index_degraded: { icon: Database, tone: "warning" },
};

const OUTCOME_VERB: Record<string, string> = {
  completed: "finished",
  failed: "failed",
  stopped: "was stopped in",
};

const OUTCOME_ICON: Record<string, LucideIcon> = {
  completed: CheckCircle2,
  failed: XCircle,
  stopped: XCircle,
};

/** Human action label for a needs_you deep link, from where it lands. */
function needsYouActionLabel(path: string): string {
  if (path.includes("/chat")) return "Open agent chat";
  if (path.includes("/traces")) return "View runs";
  if (path.includes("/agents")) return "Choose model";
  return "Open";
}

export function Today() {
  const navigate = useNavigate();
  const [home, setHome] = useState<HomeData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [askText, setAskText] = useState("");
  const [askAgentId, setAskAgentId] = useState("");
  const [asking, setAsking] = useState(false);
  const askRef = useRef<HTMLTextAreaElement>(null);

  // auto-grow the ask textarea (up to ~8 lines, then scrolls)
  useEffect(() => {
    const el = askRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight}px`;
  }, [askText]);

  const load = useCallback(() => {
    const ctrl = new AbortController();
    api
      .getHome(ctrl.signal)
      .then(setHome)
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(e?.message ?? "Couldn't load your workspace");
      });
    return ctrl;
  }, []);

  useEffect(() => {
    const ctrl = load();
    return () => ctrl.abort();
  }, [load]);

  const agents = useMemo(() => home?.agents ?? [], [home]);
  // home payload is recency-sorted (running first) — the first runnable
  // agent IS the latest-run agent.
  const defaultAskAgent = useMemo(
    () => agents.find((a) => a.status !== "needs_setup" && a.status !== "paused")?.id ?? agents[0]?.id ?? "",
    [agents],
  );
  const askAgent = askAgentId || defaultAskAgent;

  const submitAsk = async () => {
    const text = askText.trim();
    if (!text || !askAgent || asking) return;
    setAsking(true);
    try {
      const resp = await api.sendMessage(askAgent, text, false, undefined, undefined, undefined, true);
      navigate(`/agents/${askAgent}/chat?session=${resp.session_id}`);
    } catch {
      setAsking(false);
    }
  };

  const dismissNeedsYou = async (item: NeedsYouItem) => {
    await api.markNotificationRead(item.notification_id).catch(() => {});
    setHome((h) =>
      h ? { ...h, needs_you: h.needs_you.filter((n) => n.notification_id !== item.notification_id) } : h,
    );
  };

  const logout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="today"
        onLogout={logout}
        collapsed={false}
        onToggleCollapse={() => {}}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <PageHeader
          breadcrumbs={[{ label: "Workspace" }, { label: "Today" }]}
          title="Today"
          subtitle="What your agents did, and what they're waiting on."
          trailing={<CommandBar className="h-[34px] text-[13px]" />}
        />

        <div className="px-8 pb-10">
          <div className="mx-auto max-w-6xl">
            <form
              data-tour="composer"
              className="mt-1 flex items-center gap-2 rounded-lg border border-line bg-surface py-1.5 pl-4 pr-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                void submitAsk();
              }}
            >
              <textarea
                ref={askRef}
                value={askText}
                onChange={(e) => setAskText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (askText.trim() && askAgent && !asking) void submitAsk();
                  }
                }}
                rows={1}
                placeholder={
                  agents.length ? "Ask an agent to do something…" : "Create an agent first"
                }
                disabled={!agents.length}
                className="max-h-[160px] min-h-[30px] min-w-0 flex-1 resize-none self-center bg-transparent py-1 text-[14px] leading-[20px] text-ink outline-none placeholder:text-ink-faint"
              />
              <Select
                value={askAgent}
                onChange={setAskAgentId}
                options={agents.map((a) => ({ value: a.id, label: a.name }))}
                ariaLabel="Agent"
                className="h-8 shrink-0 cursor-pointer rounded-md border border-line bg-surface px-2 text-[12px] font-medium text-ink outline-none hover:bg-sunken"
              />
              <Button type="submit" disabled={!askText.trim() || !askAgent || asking}>
                {asking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SendHorizonal className="h-3.5 w-3.5" />}
                Send
              </Button>
            </form>

            {error && (
              <WarningBanner tone="danger" className="mt-4" title="Today didn't load">
                {error}
              </WarningBanner>
            )}

            <div className="mt-5 grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
              {/* Left column — attention + activity */}
              <div className="min-w-0 space-y-4 lg:col-span-2">
                {/* Needs you */}
                <section data-tour="needs-you" className="overflow-hidden rounded-lg border border-line bg-surface">
                  <div className="flex items-center justify-between px-4 py-3">
                    <h2 className="text-[16px] font-semibold leading-6 text-ink">Needs you</h2>
                    {home && home.needs_you.length > 0 && (
                      <span className="text-[12px] font-medium text-accent">
                        {home.needs_you.length} item{home.needs_you.length === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                  {home === null ? (
                    <RowsSkeleton />
                  ) : home.needs_you.length === 0 ? (
                    <EmptyState
                      icon={Bell}
                      title="Nothing needs you"
                      className="m-3 mt-0"
                    >
                      Approvals, questions, and failed runs land here — you can work from this page alone.
                    </EmptyState>
                  ) : (
                    <div className="divide-y divide-line">
                      {home.needs_you.map((item) => {
                        const meta = KIND_META[item.kind] ?? { icon: Bell, tone: "sunken" as const };
                        return (
                          <ListRow
                            key={item.notification_id}
                            leading={<IconTile icon={meta.icon} size="md" tone={meta.tone} />}
                            title={item.title}
                            sub={
                              <>
                                {item.agent_name && <span className="font-medium">{item.agent_name} · </span>}
                                {item.detail}
                              </>
                            }
                            trailing={
                              <>
                                {item.action_path && (
                                  <Button size="sm" onClick={() => navigate(item.action_path!)}>
                                    {needsYouActionLabel(item.action_path)}
                                  </Button>
                                )}
                                <Button size="sm" variant="outline" onClick={() => void dismissNeedsYou(item)}>
                                  <Check className="h-3.5 w-3.5" />
                                  Dismiss
                                </Button>
                              </>
                            }
                          />
                        );
                      })}
                    </div>
                  )}
                </section>

                {/* What happened */}
                <section className="overflow-hidden rounded-lg border border-line bg-surface">
                  <div className="flex items-center justify-between px-4 pb-1 pt-3">
                    <div>
                      <h2 className="text-[16px] font-semibold leading-6 text-ink">What happened</h2>
                      <p className="mt-0.5 text-[12px] text-ink-muted">
                        Everything your agents did since you last looked, from the audit record.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => navigate("/traces")}
                      className="cursor-pointer text-[13px] font-medium text-accent transition-colors hover:text-ink"
                    >
                      Open Traces
                    </button>
                  </div>
                  {home === null ? (
                    <RowsSkeleton />
                  ) : home.happened.length === 0 ? (
                    <EmptyState icon={CheckCircle2} title="Quiet week" className="m-3">
                      Finished and failed runs roll up here, grouped by agent and day.
                    </EmptyState>
                  ) : (
                    <div className="mt-2 divide-y divide-line">
                      {home.happened.slice(0, 8).map((g, i) => {
                        const day = new Date(g.window_start);
                        return (
                          <ListRow
                            key={`${g.agent_id}-${g.outcome}-${i}`}
                            onClick={() => navigate(`/traces/${g.agent_id}`)}
                            leading={
                              <IconTile
                                icon={OUTCOME_ICON[g.outcome] ?? CheckCircle2}
                                size="md"
                                tone={g.outcome === "failed" ? "danger" : g.outcome === "stopped" ? "warning" : "accent"}
                              />
                            }
                            title={
                              <>
                                <span className="font-medium">{g.agent_name}</span> {OUTCOME_VERB[g.outcome]}{" "}
                                {g.count} run{g.count === 1 ? "" : "s"}
                              </>
                            }
                            sub={g.outcome === "failed" ? "See Traces for what went wrong." : "Completed runs, rolled up."}
                            trailing={
                              <span className="text-[12px] text-ink-muted">
                                {day.toLocaleDateString(undefined, { month: "short", day: "numeric" })},{" "}
                                {formatClock(g.window_start)}–{formatClock(g.window_end)}
                              </span>
                            }
                          />
                        );
                      })}
                    </div>
                  )}
                  {home && home.counts.agents_running === 0 && (
                    <p className="border-t border-line px-4 py-2.5 text-[12px] text-ink-muted">
                      Nothing is running right now.
                    </p>
                  )}
                </section>
              </div>

              {/* Right rail — egress + agents */}
              <div className="min-w-0 space-y-4">
                {/* What can leave this machine */}
                <section className="overflow-hidden rounded-lg border border-line bg-surface">
                  <div className="px-4 pb-1 pt-3">
                    <h2 className="flex items-center gap-2 text-[16px] font-semibold leading-6 text-ink">
                      <ShieldCheck className="h-4 w-4 text-ink-muted" />
                      What can leave this machine
                    </h2>
                    <p className="mt-0.5 text-[12px] text-ink-muted">
                      Only what you have connected. Everything else stays here.
                    </p>
                  </div>
                  {home === null ? (
                    <RowsSkeleton />
                  ) : (
                    <div className="mt-2 divide-y divide-line">
                      <div className="px-4 py-2.5">
                        <div className="flex items-baseline justify-between">
                          <span className="text-[13px] font-medium text-ink">Prompts to model providers</span>
                          <span className="text-[12px] text-ink-muted">
                            {home.egress.providers.length} connected
                          </span>
                        </div>
                        {home.egress.providers.length > 0 && (
                          <p className="mt-0.5 truncate text-[12px] text-ink-muted">
                            {home.egress.providers.map((p) => p.name).join(", ")}
                          </p>
                        )}
                      </div>
                      <div className="px-4 py-2.5">
                        <div className="flex items-baseline justify-between">
                          <span className="text-[13px] font-medium text-ink">Requests to tools</span>
                          <span className="text-[12px] text-ink-muted">
                            {home.egress.mcps.length} connected
                          </span>
                        </div>
                        {home.egress.mcps.length > 0 && (
                          <p className="mt-0.5 truncate text-[12px] text-ink-muted">
                            {home.egress.mcps.map((m) => m.name).join(", ")}
                          </p>
                        )}
                      </div>
                      <div className="px-4 py-2.5">
                        <div className="flex items-baseline justify-between">
                          <span className="text-[13px] font-medium text-ink">Messages through channels</span>
                          <span className="text-[12px] text-ink-muted">
                            {home.egress.channels.every((c) => !c.connected)
                              ? "Paused"
                              : `${home.egress.channels.filter((c) => c.connected).length} live`}
                          </span>
                        </div>
                        {home.egress.channels.length > 0 && (
                          <p className="mt-0.5 truncate text-[12px] text-ink-muted">
                            {home.egress.channels.map((c) => c.platform).join(", ")}
                          </p>
                        )}
                      </div>
                      <p className="px-4 py-2.5 text-[12px] text-ink-muted">
                        <span className="font-medium text-ink">Stays here:</span> configuration, memory,
                        credentials, workspace files and run history.
                      </p>
                    </div>
                  )}
                </section>

                {/* Your agents */}
                <section className="overflow-hidden rounded-lg border border-line bg-surface">
                  <div className="flex items-center justify-between px-4 py-3">
                    <h2 className="text-[16px] font-semibold leading-6 text-ink">Your agents</h2>
                    {home && (
                      <span className="text-[12px] text-ink-muted">
                        {home.counts.agents_running} running
                      </span>
                    )}
                  </div>
                  {home === null ? (
                    <RowsSkeleton />
                  ) : agents.length === 0 ? (
                    <EmptyState
                      icon={Bot}
                      title="No agents yet"
                      className="m-3 mt-0"
                      action={
                        <Button size="sm" onClick={() => navigate("/agents")}>
                          Create your first agent
                        </Button>
                      }
                    >
                      An agent gets a workspace, a model, and the tools you allow.
                    </EmptyState>
                  ) : (
                    <>
                      <div className="divide-y divide-line">
                        {agents.map((agent) => (
                          <ListRow
                            key={agent.id}
                            onClick={() => navigate(`/agents/${agent.id}/chat`)}
                            leading={
                              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-tint text-[13px] font-semibold text-accent">
                                {agent.name.slice(0, 1).toUpperCase()}
                              </div>
                            }
                            title={agent.name}
                            trailing={
                              agent.status === "needs_setup" ? (
                                <span className="text-[12px] font-medium text-warning">Needs a model</span>
                              ) : (
                                <span className="text-[12px] text-ink-muted">
                                  {agent.status === "running" ? "Running" : "Idle"}
                                  {agent.last_run_at
                                    ? ` · last run ${new Date(agent.last_run_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
                                    : ""}
                                </span>
                              )
                            }
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => navigate("/agents")}
                        className="block w-full cursor-pointer border-t border-line px-4 py-2.5 text-left text-[13px] font-medium text-accent transition-colors hover:bg-sunken"
                      >
                        See all {agents.length} agents →
                      </button>
                    </>
                  )}
                </section>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function RowsSkeleton() {
  return (
    <div className="space-y-2.5 px-4 py-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-9 animate-pulse rounded bg-sunken" />
      ))}
    </div>
  );
}
