import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bot,
  Download,
  MoreHorizontal,
  Plus,
  Settings as SettingsIcon,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentActivity, AgentActivityData } from "@/lib/api";
import type { Agent, Provider } from "@/lib/types";
import {
  DashboardSidebar,
  NAV_ROUTES,
  type NavKey,
} from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { FilterPills } from "@/components/ui/filter-pills";
import { CardGrid } from "@/components/ui/card-grid";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusWord, type StatusKind } from "@/components/ui/status-word";
import { CommandBar } from "@/components/ui/command-bar";
import { Button } from "@/components/ui/button";
import { CreateAgentModal } from "@/components/CreateAgentModal";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { SettingsOverlay } from "@/components/SettingsOverlay";
import { Select } from "@/components/ui/select";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";

type FilterKey = "all" | "active" | "needs_setup" | "disabled";
type SortKey = "recent" | "name";

function needsSetup(a: Agent) {
  return !a.model || !a.provider_id;
}

function statusOf(a: Agent, act?: AgentActivity): StatusKind {
  if ((act?.running ?? 0) > 0) return "running";
  if (!a.enabled) return "paused";
  if (needsSetup(a)) return "needs_setup";
  return "idle";
}

export function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activity, setActivity] = useState<AgentActivityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createMode, setCreateMode] = useState<"form" | "yaml">("form");
  const [showSettings, setShowSettings] = useState(false);
  const [settingsAgent, setSettingsAgent] = useState<Agent | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("recent");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadAll = async () => {
    try {
      const [list, act] = await Promise.all([
        api.listAgents(),
        api.getAgentActivity(),
      ]);
      setAgents(list);
      setActivity(act);
    } catch {
      navigate("/login");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    api.listProviders().then(setProviders).catch(() => {});
    const interval = setInterval(
      () => api.getAgentActivity().then(setActivity).catch(() => {}),
      10000,
    );
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const act = (id: string) => activity?.agents[id];

  const filtered = useMemo(() => {
    let list = agents;
    if (filter === "active")
      list = agents.filter((a) => a.enabled && !needsSetup(a));
    else if (filter === "needs_setup") list = agents.filter(needsSetup);
    else if (filter === "disabled") list = agents.filter((a) => !a.enabled);
    return [...list].sort((x, y) => {
      if (sort === "name") return x.name.localeCompare(y.name);
      const ax = act(x.id)?.last_activity_at ?? "";
      const ay = act(y.id)?.last_activity_at ?? "";
      return ay.localeCompare(ax); // most recent first; never-run sinks
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, activity, filter, sort]);

  const counts = useMemo(
    () => ({
      all: agents.length,
      active: agents.filter((a) => a.enabled && !needsSetup(a)).length,
      needs_setup: agents.filter(needsSetup).length,
      disabled: agents.filter((a) => !a.enabled).length,
    }),
    [agents],
  );

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => navigate(NAV_ROUTES[page]);

  const openChat = (agent: Agent) => {
    navigate(`/agents/${agent.id}/chat`);
  };

  const openSettings = (agent: Agent) => {
    setSettingsAgent(agent);
    setShowSettings(true);
  };


  const weekDelta =
    (activity?.sessions_this_week ?? 0) - (activity?.sessions_prev_week ?? 0);

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="agents"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        agentCount={agents.length}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Workspace" }, { label: "Agents" }]}
          title="Agents"
          subtitle="Everything your workspace can do on its own, at a glance."
          trailing={<CommandBar className="h-[34px] text-[13px]" />}
          actions={
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setCreateMode("yaml");
                  setShowCreate(true);
                }}
              >
                <Download className="h-4 w-4" />
                Import
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setCreateMode("form");
                  setShowCreate(true);
                }}
              >
                <Plus className="h-4 w-4" />
                New agent
              </Button>
            </>
          }
        />

        <div className="px-8 pt-4">
          <PageIntro def={INTRO_BY_KEY.agents} />
        </div>

        <div className="px-8 pb-4">
          {/* stat cards */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Active agents"
              value={counts.active}
              sublabel={`of ${agents.length}`}
            />
            <StatCard
              label="Running now"
              value={activity?.running_now ?? 0}
              sublabel={activity?.running_names.join(", ") || "none"}
            />
            <StatCard
              label="Sessions this week"
              value={activity?.sessions_this_week ?? 0}
              sublabel={
                <span className="inline-flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  {weekDelta >= 0 ? `+${weekDelta}` : weekDelta} vs last
                </span>
              }
            />
            <StatCard
              label="Needs attention"
              value={
                <span className={counts.needs_setup > 0 ? "text-warning" : undefined}>
                  {counts.needs_setup}
                </span>
              }
              sublabel={
                counts.needs_setup > 0 ? "no model set" : "all configured"
              }
            />
          </div>

          {/* filter + sort */}
          <div className="mt-6 flex items-center justify-between gap-4">
            <FilterPills
              variant="segmented"
              active={filter}
              onChange={(k) => setFilter(k as FilterKey)}
              pills={[
                { key: "all", label: "All", count: counts.all },
                { key: "active", label: "Active", count: counts.active },
                {
                  key: "needs_setup",
                  label: "Needs setup",
                  count: counts.needs_setup,
                },
                {
                  key: "disabled",
                  label: "Disabled",
                  count: counts.disabled,
                },
              ]}
            />
            <label className="flex items-center gap-1.5 text-[13px] text-ink-muted">
              Sort:
              <Select
                value={sort}
                onChange={(v) => setSort(v as SortKey)}
                options={[
                  { value: "recent", label: "recent activity" },
                  { value: "name", label: "name A–Z" },
                ]}
                className="h-[34px] cursor-pointer rounded-md border border-line bg-surface px-2 text-[13px] text-ink"
              />
            </label>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-8 pb-10">
          {/* cards */}
          <div>
            {loading ? (
              <CardGrid>
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="h-[190px] animate-pulse rounded-[16px] border border-line bg-surface"
                  />
                ))}
              </CardGrid>
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={Bot}
                title={
                  agents.length === 0
                    ? "No agents yet"
                    : "No agents match this filter"
                }
                action={
                  agents.length === 0 ? (
                    <Button size="sm" onClick={() => setShowCreate(true)}>
                      <Plus className="h-4 w-4" />
                      New agent
                    </Button>
                  ) : undefined
                }
              >
                {agents.length === 0
                  ? "Create your first agent — it only needs a name and a model."
                  : "Try a different filter above."}
              </EmptyState>
            ) : (
              <CardGrid>
                {filtered.map((agent) => (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    activity={act(agent.id)}
                    menuOpen={menuFor === agent.id}
                    onToggleMenu={() =>
                      setMenuFor(menuFor === agent.id ? null : agent.id)
                    }
                    onOpenChat={() => openChat(agent)}
                    onChooseModel={() => openSettings(agent)}
                    onSettings={() => {
                      setMenuFor(null);
                      openSettings(agent);
                    }}
                    onEnable={async () => {
                      await api.enableAgent(agent.id);
                      await loadAll();
                    }}
                  />
                ))}
              </CardGrid>
            )}
          </div>
        </div>
      </div>

      <CreateAgentModal
        open={showCreate}
        initialMode={createMode}
        onClose={() => setShowCreate(false)}
        onCreated={(id) => {
          setShowCreate(false);
          loadAll();
          navigate(`/agents/${id}/chat`);
        }}
        providers={providers}
      />

      <SettingsOverlay
        agent={settingsAgent}
        open={showSettings}
        onClose={() => setShowSettings(false)}
        onSaved={() => loadAll()}
        providers={providers}
      />
    </div>
  );
}

function AgentCard({
  agent,
  activity,
  menuOpen,
  onToggleMenu,
  onOpenChat,
  onChooseModel,
  onSettings,
  onEnable,
}: {
  agent: Agent;
  activity: AgentActivity | undefined;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onOpenChat: () => void;
  onChooseModel: () => void;
  onSettings: () => void;
  onEnable: () => void;
}) {
  const status = statusOf(agent, activity);
  const persona = agent.persona || agent.task;

  return (
    <div
      data-agent-name={agent.name}
      className={cn(
        "flex flex-col rounded-[16px] border border-line bg-surface p-5",
        status === "paused" && "opacity-70",
      )}
    >
      {/* header: tile + name/model + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] bg-accent-tint text-[17px] font-semibold text-accent">
            {agent.name.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0">
            <div className="truncate text-[16px] font-semibold leading-[24px] text-ink">
              {agent.name}
            </div>
            <div className="truncate font-mono text-[12px] leading-[16px] text-ink-muted">
              {agent.model ?? "No model"}
            </div>
          </div>
        </div>
        <StatusWord
          status={status}
          label={
            status === "needs_setup"
              ? "Setup needed"
              : status === "paused"
                ? "Disabled"
                : undefined
          }
        />
      </div>

      {/* persona line */}
      <div className="mt-3 min-h-[20px]">
        {persona ? (
          <p className="truncate text-[14px] leading-[20px] text-ink-muted">
            {persona}
          </p>
        ) : (
          <button
            type="button"
            onClick={onChooseModel}
            className="cursor-pointer text-[14px] leading-[20px] text-accent underline decoration-dotted underline-offset-2 hover:decoration-solid"
          >
            + Add a persona so it knows what it is for
          </button>
        )}
      </div>

      {/* footer: sparkline + stats + actions */}
      <div className="mt-4 flex items-end justify-between gap-3 border-t border-line pt-4">
        <div className="flex items-end gap-3">
          <Sparkline days={activity?.sessions_7d ?? []} />
          <div className="text-[12px] leading-[18px] text-ink-muted">
            <div className="text-[15px] font-medium text-ink">
              {activity?.sessions ?? 0}
            </div>
            <div>
              {activity?.running ? (
                <span className="text-success">running now</span>
              ) : (
                <>
                  sessions
                  <br />
                </>
              )}
            </div>
            <div>
              {activity?.last_activity_at
                ? formatRelative(activity.last_activity_at)
                : "no activity"}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {status === "needs_setup" ? (
            <Button size="sm" onClick={onChooseModel}>
              Choose model
            </Button>
          ) : status === "paused" ? (
            <Button size="sm" variant="outline" onClick={onEnable}>
              Enable
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={onOpenChat}>
              Open chat
            </Button>
          )}
          <div className="relative">
            <button
              type="button"
              aria-label={`${agent.name} options`}
              onClick={onToggleMenu}
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-sunken hover:text-ink"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-9 z-20 min-w-[140px] rounded-md border border-line bg-surface p-1 shadow-lg">
                <button
                  type="button"
                  onClick={onSettings}
                  className="flex w-full cursor-pointer items-center gap-2 rounded px-2.5 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-sunken"
                >
                  <SettingsIcon className="h-3.5 w-3.5" />
                  Settings
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Sparkline({ days }: { days: number[] }) {
  const max = Math.max(...days, 1);
  const empty = days.every((d) => d === 0);
  return (
    <div
      className="flex h-8 items-end gap-[3px]"
      aria-label="Sessions per day, last 7 days"
    >
      {days.map((d, i) => (
        <span
          key={i}
          className={cn(
            "w-[5px] rounded-[1.5px]",
            empty
              ? "border-t border-dashed border-line"
              : i === 6
                ? "bg-accent"
                : "bg-track",
          )}
          style={
            empty
              ? { height: 0 }
              : { height: `${Math.max(14, (d / max) * 100)}%` }
          }
        />
      ))}
    </div>
  );
}
