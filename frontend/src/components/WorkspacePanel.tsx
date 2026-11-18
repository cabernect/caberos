import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Search,
} from "lucide-react";
import { api, workspaceBackend, type PreviewSource } from "@/lib/api";
import type { Citation, RunSummary, WorkspaceEntry } from "@/lib/types";
import { formatRelative } from "@/lib/time";
import { PreviewPanel } from "@/components/previews/PreviewPanel";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterPills } from "@/components/ui/filter-pills";
import { Input } from "@/components/ui/input";
import { StatusWord, type StatusKind } from "@/components/ui/status-word";

type PanelTab = "run" | "workspace" | "sources";

interface WorkspacePanelProps {
  agentId: string;
  agentName: string;
  sessionId: string | null;
  /** Canonical root the session is pinned to — shown as the panel's origin. */
  workspacePath?: string | null;
  selected: PreviewSource | null;
  onSelect: (source: PreviewSource | null) => void;
  /** Workspace paths this session's runs created or modified — tree dot. */
  changedPaths: Set<string>;
  citations: Citation[];
  runStatus: string | null;
  /** PreviewPanel revise drafts — the page prefills the chat composer. */
  onRevise?: (draft: string) => void;
}

export function WorkspacePanel({
  agentId,
  agentName,
  sessionId,
  workspacePath,
  selected,
  onSelect,
  changedPaths,
  citations,
  runStatus,
  onRevise,
}: WorkspacePanelProps) {
  const [tab, setTab] = useState<PanelTab>("workspace");
  const [filter, setFilter] = useState("");
  const [filesOpen, setFilesOpen] = useState(true);
  const filesId = useId();
  // Stable backend object — a fresh one every render would invalidate
  // PreviewPanel's memoized identity and refetch image/pdf blobs in a loop.
  const previewBackend = useMemo(
    () => workspaceBackend(agentId, sessionId ?? undefined),
    [agentId, sessionId],
  );

  return (
    <div className="@container/workspace flex h-full min-h-0 min-w-0 flex-col border-l border-line bg-surface">
      {/* Tab strip — Run | Workspace | Sources, with the folder kind on
          the right like the mockup's "Caber · persistent folder".
          py-3 makes the strip 59px — flush with the chat header's
          bottom border so the two horizontal lines align. */}
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-3">
        <FilterPills
          variant="segmented"
          pills={[
            { key: "run", label: "Run" },
            { key: "workspace", label: "Workspace" },
            { key: "sources", label: "Sources" },
          ]}
          active={tab}
          onChange={(v) => setTab(v as PanelTab)}
          className="shrink-0 [&_button]:focus-visible:outline-2 [&_button]:focus-visible:outline-offset-2 [&_button]:focus-visible:outline-ring"
        />
        <span
          className="min-w-0 flex-1 truncate text-right text-xs text-ink-faint"
          title={workspacePath ?? undefined}
        >
          {agentName} · {workspacePath ?? "persistent folder"}
        </span>
        {tab === "workspace" && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={filesOpen ? "Hide files" : "Show files"}
            title={filesOpen ? "Hide files" : "Show files"}
            aria-expanded={filesOpen}
            aria-controls={filesId}
            onClick={() => setFilesOpen((open) => !open)}
            className="text-ink-muted"
          >
            <FolderOpen aria-hidden="true" />
          </Button>
        )}
        {/* No ✕ — the chat header's panel toggle hides/shows this whole
            panel; a second close here was redundant chrome. */}
      </div>

      {tab === "workspace" && (
        <div className="flex min-h-0 flex-1 flex-col @min-[640px]/workspace:flex-row">
          {/* Preview column — left; the file picker sits on the right. */}
          <div className={`${selected || !filesOpen ? "flex" : "hidden @min-[640px]/workspace:flex"} min-h-0 min-w-0 flex-1 flex-col`}>
            {selected ? (
              <PreviewPanel
                agentId={agentId}
                source={selected}
                backend={previewBackend}
                onClose={() => onSelect(null)}
                onRevise={onRevise}
                className="h-full border-0"
              />
            ) : (
              <EmptyState
                icon={FileText}
                title="File preview"
                className="min-h-0 flex-1 rounded-none border-0 px-4 py-8"
                action={!filesOpen && (
                  <Button variant="outline" size="sm" onClick={() => setFilesOpen(true)}>
                    Browse files
                  </Button>
                )}
              >
                Select a file to preview it here.
              </EmptyState>
            )}
          </div>

          {/* File tree column — right. h-12 header matches the preview
              header so the two divider lines sit on the same row. */}
          <div
            id={filesId}
            aria-label="Workspace files"
            role="region"
            hidden={!filesOpen}
            className={`${filesOpen ? "flex" : "hidden"} ${selected ? "max-h-48 shrink-0" : "min-h-0 flex-1"} w-full flex-col border-t border-line @min-[640px]/workspace:max-h-none @min-[640px]/workspace:w-48 @min-[640px]/workspace:flex-none @min-[640px]/workspace:border-t-0 @min-[640px]/workspace:border-l`}
          >
            <div className="flex h-12 shrink-0 items-center border-b border-line px-3">
              <div className="relative w-full">
                <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                <Input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Find file"
                  aria-label="Find file"
                  className="bg-ground pl-8 text-xs md:text-xs"
                />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
              <WorkspaceTree
                agentId={agentId}
                sessionId={sessionId}
                filter={filter}
                selectedPath={selected?.path ?? null}
                changedPaths={changedPaths}
                onSelect={onSelect}
              />
            </div>
            {changedPaths.size > 0 && (
              <div className="shrink-0 border-t border-line px-3 py-2 text-xs text-ink-muted">
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" />
                changed in this chat
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
                    className="block rounded-md px-3 py-2 transition-colors hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
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
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/traces/${agentId}/${lastRun.id}`)}
              className="h-9 w-full justify-between rounded-none border-t border-line px-3 text-xs text-accent"
            >
              View trace
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
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
      <span className="shrink-0 text-xs text-ink-faint">{label}</span>
      <span
        className={
          tone === "danger"
            ? "truncate text-right font-mono text-[12px] text-danger"
            : "truncate text-right font-mono text-[12px] text-ink-muted"
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
  sessionId,
  filter,
  selectedPath,
  changedPaths,
  onSelect,
}: {
  agentId: string;
  sessionId: string | null;
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
        const r = await api.listWorkspace(
          agentId,
          dirPath || undefined,
          sessionId ?? undefined,
        );
        setChildren((prev) => ({ ...prev, [dirPath]: r.entries ?? [] }));
      } catch {
        setChildren((prev) => ({ ...prev, [dirPath]: [] }));
      }
    },
    [agentId, sessionId],
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
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggle(path)}
              aria-expanded={open}
              className="w-full justify-start gap-1 rounded-sm px-1.5 text-left text-xs font-normal text-ink-muted"
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
            </Button>
            {open && <div>{renderDir(path, depth + 1)}</div>}
          </div>
        );
      }
      const changed = changedPaths.has(path);
      const active = selectedPath === path;
      return (
        <Button
          variant="ghost"
          size="sm"
          key={path}
          onClick={() =>
            onSelect({ path, sessionId: sessionId ?? undefined })
          }
          title={path}
          aria-current={active ? "true" : undefined}
          className={`w-full justify-start gap-1 rounded-sm px-1.5 text-left text-xs font-normal ${
            active
              ? "bg-accent-tint text-ink hover:bg-accent-tint"
              : "text-ink-muted"
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
        </Button>
      );
    });
  };

  return <div>{renderDir("", 0)}</div>;
}
