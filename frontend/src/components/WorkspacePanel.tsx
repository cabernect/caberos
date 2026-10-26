import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Search,
  X,
} from "lucide-react";
import { api, type PreviewSource } from "@/lib/api";
import type { Citation, RunSummary, WorkspaceEntry } from "@/lib/types";
import { formatRelative } from "@/lib/time";
import { PreviewPanel } from "@/components/previews/PreviewPanel";
import { FilterPills } from "@/components/ui/filter-pills";
import { StatusWord, type StatusKind } from "@/components/ui/status-word";

type PanelTab = "run" | "workspace" | "sources";

interface WorkspacePanelProps {
  agentId: string;
  agentName: string;
  sessionId: string | null;
  selected: PreviewSource | null;
  onSelect: (source: PreviewSource | null) => void;
  /** Workspace paths this session's runs created or modified — tree dot. */
  changedPaths: Set<string>;
  citations: Citation[];
  runStatus: string | null;
  onClose: () => void;
}

export function WorkspacePanel({
  agentId,
  agentName,
  sessionId,
  selected,
  onSelect,
  changedPaths,
  citations,
  runStatus,
  onClose,
}: WorkspacePanelProps) {
  const [tab, setTab] = useState<PanelTab>("workspace");
  const [filter, setFilter] = useState("");

  return (
    <div className="flex h-full min-w-0 flex-col border-l border-line bg-surface">
      {/* Tab strip — Run | Workspace | Sources, with the folder kind on
          the right like the mockup's "Caber · persistent folder". */}
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <FilterPills
          variant="segmented"
          pills={[
            { key: "run", label: "Run" },
            { key: "workspace", label: "Workspace" },
            { key: "sources", label: "Sources" },
          ]}
          active={tab}
          onChange={(v) => setTab(v as PanelTab)}
        />
        <span className="ml-auto truncate text-[11px] text-ink-faint">
          {agentName} · persistent folder
        </span>
        <button
          onClick={onClose}
          className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-[6px] text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
          title="Close workspace panel"
          aria-label="Close workspace panel"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {tab === "workspace" && (
        <div className="flex min-h-0 flex-1">
          {/* File tree column */}
          <div className="flex w-[190px] shrink-0 flex-col border-r border-line">
            <div className="border-b border-line p-2">
              <div className="flex items-center gap-1.5 rounded-[8px] border border-line bg-ground px-2 py-1.5">
                <Search className="h-3 w-3 shrink-0 text-ink-faint" />
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Find file"
                  className="w-full bg-transparent text-[12px] text-ink outline-none placeholder:text-ink-faint"
                />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
              <WorkspaceTree
                agentId={agentId}
                filter={filter}
                selectedPath={selected?.path ?? null}
                changedPaths={changedPaths}
                onSelect={onSelect}
              />
            </div>
            {changedPaths.size > 0 && (
              <div className="border-t border-line px-3 py-2 text-[10px] text-ink-faint">
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" />
                changed in this chat
              </div>
            )}
          </div>

          {/* Preview column */}
          <div className="flex min-w-0 flex-1 flex-col">
            {selected ? (
              <PreviewPanel
                agentId={agentId}
                source={selected}
                onClose={() => onSelect(null)}
                className="h-full border-0"
              />
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
                <FileText className="h-6 w-6 text-ink-faint" />
                <p className="text-[12px] text-ink-muted">
                  Select a file to preview it here.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "run" && (
        <RunTab
          agentId={agentId}
          sessionId={sessionId}
          runStatus={runStatus}
        />
      )}

      {tab === "sources" && (
        <div className="flex-1 overflow-y-auto p-3">
          {citations.length === 0 ? (
            <p className="p-2 text-[12px] text-ink-muted">
              No sources yet. Pages the agent opens during a run appear here.
            </p>
          ) : (
            <ol className="space-y-1.5">
              {citations.map((c, i) => (
                <li key={c.id || i}>
                  <a
                    href={c.source_path}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-[8px] px-2.5 py-2 transition-colors hover:bg-sunken"
                  >
                    <span className="mr-1.5 text-[11px] text-ink-faint">
                      [{i + 1}]
                    </span>
                    <span className="text-[13px] text-accent underline decoration-accent/40 underline-offset-2">
                      {c.title || c.source_path}
                    </span>
                  </a>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

/* Run tab — shows the session's active run or, once it finishes, the most
   recent one, so the tab never sits empty. Fetches the latest run for this
   session each time the tab opens or the live status flips; deep-links to
   the full trace. */
function RunTab({
  agentId,
  sessionId,
  runStatus,
}: {
  agentId: string;
  sessionId: string | null;
  runStatus: string | null;
}) {
  const navigate = useNavigate();
  const [lastRun, setLastRun] = useState<RunSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const live =
    runStatus === "running" || runStatus === "awaiting_approval"
      ? runStatus
      : null;

  // Refetch whenever the live status flips — running → done picks up the
  // final state; done → running picks up the new run.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true);
    api
      .listRuns({ agent_id: agentId, session_id: sessionId, limit: 1 })
      .then((runs) => {
        if (!cancelled) setLastRun(runs[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setLastRun(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, sessionId, runStatus]);

  // 1s ticker for the live elapsed readout.
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);

  const statusKind: { kind: StatusKind; label: string } = (() => {
    if (live)
      return live === "awaiting_approval"
        ? { kind: "running", label: "Awaiting approval" }
        : { kind: "running", label: "Running" };
    if (!lastRun) return { kind: "idle", label: "Idle" };
    const byStatus: Record<string, { kind: StatusKind; label: string }> = {
      completed: { kind: "success", label: "Completed" },
      failed: { kind: "failed", label: "Failed" },
      stopped: { kind: "idle", label: "Stopped" },
      interrupted: { kind: "idle", label: "Interrupted" },
      running: { kind: "running", label: "Running" },
      awaiting_approval: { kind: "running", label: "Awaiting approval" },
    };
    return byStatus[lastRun.status] ?? { kind: "idle", label: lastRun.status };
  })();

  const durationMs = (() => {
    if (!lastRun) return null;
    if (live) {
      const start = new Date(lastRun.started_at).getTime();
      return Number.isFinite(start) ? Math.max(0, now - start) : null;
    }
    if (lastRun.latency_ms != null && lastRun.latency_ms > 0)
      return lastRun.latency_ms;
    if (lastRun.completed_at) {
      const ms =
        new Date(lastRun.completed_at).getTime() -
        new Date(lastRun.started_at).getTime();
      return ms >= 0 ? ms : null;
    }
    return null;
  })();

  return (
    <div className="flex-1 overflow-y-auto p-3">
      <div className="overflow-hidden rounded-[10px] border border-line bg-surface">
        <div className="flex items-center justify-between border-b border-line px-3 py-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.05em] text-ink-faint">
            {live ? "Current run" : lastRun ? "Last run" : "Run"}
          </span>
          <StatusWord status={statusKind.kind} label={statusKind.label} />
        </div>

        {!sessionId || (!loading && !lastRun && !live) ? (
          <p className="px-3 py-4 text-[12px] text-ink-muted">
            No runs in this chat yet. Send a message to start one.
          </p>
        ) : lastRun ? (
          <div>
            <RunKV label="Trigger" value={lastRun.trigger} />
            <RunKV
              label="Started"
              value={formatRelative(lastRun.started_at)}
              title={lastRun.started_at}
            />
            <RunKV
              label="Duration"
              value={
                durationMs != null
                  ? live
                    ? `${formatDuration(durationMs)} elapsed`
                    : formatDuration(durationMs)
                  : "—"
              }
            />
            <RunKV
              label="Tokens"
              value={
                lastRun.tokens_in || lastRun.tokens_out
                  ? `${lastRun.tokens_in.toLocaleString()} in · ${lastRun.tokens_out.toLocaleString()} out`
                  : "—"
              }
            />
            {lastRun.cost > 0 && (
              <RunKV label="Cost" value={`$${lastRun.cost.toFixed(4)}`} />
            )}
            {lastRun.error && (
              <RunKV label="Error" value={lastRun.error} tone="danger" />
            )}
            <button
              type="button"
              onClick={() => navigate(`/traces/${agentId}/${lastRun.id}`)}
              className="flex w-full items-center justify-between border-t border-line px-3 py-2 text-left text-[12px] font-medium text-accent transition hover:bg-ground"
            >
              View trace
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <p className="px-3 py-4 text-[12px] text-ink-muted">Loading…</p>
        )}
      </div>
      <p className="mt-3 px-1 text-[12px] leading-[1.5] text-ink-muted">
        Steps stream in the chat as the run progresses. The full trace — every
        model call, tool call, and its inputs — lives in Observability.
      </p>
    </div>
  );
}

function RunKV({
  label,
  value,
  title,
  tone,
}: {
  label: string;
  value: string;
  title?: string;
  tone?: "danger";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line px-3 py-1.5 last:border-b-0">
      <span className="shrink-0 text-[12px] text-ink-3">{label}</span>
      <span
        className={
          tone === "danger"
            ? "truncate text-right font-mono text-[12px] text-danger"
            : "truncate text-right font-mono text-[12px] text-ink-2"
        }
        title={title ?? value}
      >
        {value}
      </span>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

/* Lazy file tree — each directory loads its children on first expand.
   "Find file" filters the already-loaded nodes client-side. */
function WorkspaceTree({
  agentId,
  filter,
  selectedPath,
  changedPaths,
  onSelect,
}: {
  agentId: string;
  filter: string;
  selectedPath: string | null;
  changedPaths: Set<string>;
  onSelect: (source: PreviewSource) => void;
}) {
  const [children, setChildren] = useState<Record<string, WorkspaceEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(
    async (dirPath: string) => {
      try {
        const r = await api.listWorkspace(agentId, dirPath || undefined);
        setChildren((prev) => ({ ...prev, [dirPath]: r.entries ?? [] }));
      } catch {
        setChildren((prev) => ({ ...prev, [dirPath]: [] }));
      }
    },
    [agentId],
  );

  useEffect(() => {
    load("");
  }, [load]);

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    if (!children[path]) load(path);
  };

  const q = filter.trim().toLowerCase();
  const matches = useCallback(
    (name: string) => !q || name.toLowerCase().includes(q),
    [q],
  );

  const renderDir = (dirPath: string, depth: number): React.ReactNode => {
    const entries = (children[dirPath] ?? [])
      .filter((e) => matches(e.name))
      .sort((a, b) =>
        a.type !== b.type ? (a.type === "dir" ? -1 : 1) : a.name.localeCompare(b.name),
      );
    return entries.map((e) => {
      const path = dirPath ? `${dirPath}/${e.name}` : e.name;
      if (e.type === "dir") {
        const open = expanded.has(path);
        return (
          <div key={path}>
            <button
              onClick={() => toggle(path)}
              className="flex w-full cursor-pointer items-center gap-1 rounded-[6px] px-1.5 py-1 text-left text-[12px] text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
              style={{ paddingLeft: `${6 + depth * 14}px` }}
            >
              {open ? (
                <ChevronDown className="h-3 w-3 shrink-0 text-ink-faint" />
              ) : (
                <ChevronRight className="h-3 w-3 shrink-0 text-ink-faint" />
              )}
              {open ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
              )}
              <span className="truncate">{e.name}</span>
            </button>
            {open && <div>{renderDir(path, depth + 1)}</div>}
          </div>
        );
      }
      const changed = changedPaths.has(path);
      const active = selectedPath === path;
      return (
        <button
          key={path}
          onClick={() => onSelect({ path })}
          title={path}
          className={`flex w-full cursor-pointer items-center gap-1 rounded-[6px] px-1.5 py-1 text-left text-[12px] transition-colors ${
            active
              ? "bg-accent-tint text-ink"
              : "text-ink-muted hover:bg-sunken hover:text-ink"
          }`}
          style={{ paddingLeft: `${22 + depth * 14}px` }}
        >
          <FileText className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <span className="truncate">{e.name}</span>
          {changed && (
            <span
              className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
              title="Changed in this chat"
            />
          )}
        </button>
      );
    });
  };

  return <div>{renderDir("", 0)}</div>;
}
