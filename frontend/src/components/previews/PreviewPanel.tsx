import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BookPlus,
  Download,
  ExternalLink,
  FileClock,
  FileText,
  FolderOpen,
  GitCompareArrows,
  History,
  Loader2,
  MessageSquarePlus,
  RefreshCcw,
  X,
} from "lucide-react";
import { DiffBlock } from "@/components/DiffBlock";
import { api, workspaceBackend, type PreviewBackend, type PreviewSource } from "@/lib/api";
import type { ArtifactMeta, ArtifactRevisionInfo, PreviewPayload } from "@/lib/types";
import { formatBytes, PreviewBody } from "./renderers";

const isDesktopShell =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

interface PreviewPanelProps {
  /** Owning agent — used for workspace actions (Vault, Track, revise) and
   *  the default backend. Pass "" with an explicit `backend` for surfaces
   *  that aren't workspace-scoped (e.g. skill resources). */
  agentId: string;
  /** {path} for live files, {artifactId, revisionId} for managed bytes. */
  source: PreviewSource;
  /** Content root — defaults to the agent workspace backend. Skill
   *  surfaces pass a skill backend; workspace-only actions then hide. */
  backend?: PreviewBackend;
  /** Called when the panel wants to close (Escape or ✕). */
  onClose?: () => void;
  /** Prefills the composer with a revise request — only offered where a
   *  composer exists (chat surface). */
  onAskRevise?: (artifact: ArtifactMeta) => void;
  /** Extra classes for the outer container (sizing lives with the caller). */
  className?: string;
}

/**
 * The shared preview surface — one module serves chat, Workspace, and
 * Skills. It owns the fetch lifecycle, artifact banner/actions, and
 * delegates content to the kind renderers.
 */
export function PreviewPanel({ agentId, source, backend, onClose, onAskRevise, className }: PreviewPanelProps) {
  const isWorkspace = !backend;
  // Memoize — a fresh backend object every render would retrigger the
  // fetch effect below and loop forever.
  const be = useMemo(() => backend ?? workspaceBackend(agentId), [backend, agentId]);
  // Payload is keyed to the source it was fetched for — a stale payload
  // must never render against a new source (would silently swap bytes).
  const [loaded, setLoaded] = useState<{ key: string; payload: PreviewPayload } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ArtifactRevisionInfo[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [viewing, setViewing] = useState<PreviewSource>(source);
  // Compare mode — a revision-vs-current diff replaces the content area.
  const [compare, setCompare] = useState<{
    loading: boolean;
    comparable?: boolean;
    diff?: string;
    identical?: boolean;
    reason?: string;
    fromN?: number | null;
    toN?: number | null;
    fromBytes?: number;
    toBytes?: number;
  } | null>(null);
  const historyRef = useRef<HTMLDivElement>(null);

  const sourceKey = (s: PreviewSource) =>
    `${s.path ?? ""}${s.artifactId ?? ""}${s.revisionId ?? ""}`;
  const viewingKey = sourceKey(viewing);
  const payload = loaded?.key === viewingKey ? loaded.payload : null;

  // Reset when the caller points the panel at a different file.
  useEffect(() => {
    setViewing(source);
    setLoaded(null);
    setError(null);
    setHistory(null);
    setHistoryOpen(false);
    setActionMsg(null);
    setCompare(null);
  }, [source.path, source.artifactId, source.revisionId]);

  const fetchPreview = useCallback(async () => {
    const key = sourceKey(viewing);
    setError(null);
    try {
      setLoaded({ key, payload: await be.preview(viewing) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoaded(null);
    }
  }, [be, viewing.path, viewing.artifactId, viewing.revisionId]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  // Escape closes the preview before whatever contains it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  // Close the history dropdown on outside click.
  useEffect(() => {
    if (!historyOpen) return;
    const onDown = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [historyOpen]);

  const artifact = payload?.artifact ?? null;
  const currentPath = artifact?.current_path ?? payload?.path ?? source.path ?? "";

  const openHistory = async () => {
    if (!artifact) return;
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setHistoryOpen(true);
    try {
      const res = await api.listArtifactRevisions(agentId, artifact.id);
      setHistory(res.revisions);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const viewRevision = (rev: ArtifactRevisionInfo) => {
    if (!artifact) return;
    setHistoryOpen(false);
    setCompare(null);
    setViewing({ artifactId: artifact.id, revisionId: rev.revision_id });
  };

  const backToCurrent = () => {
    if (!artifact) return;
    setCompare(null);
    setViewing({ path: artifact.current_path });
  };

  const restoreRevision = async (rev: ArtifactRevisionInfo) => {
    if (!artifact) return;
    try {
      const res = await api.restoreArtifactRevision(agentId, artifact.id, rev.revision_id);
      setActionMsg(`Restored as revision ${res.revision_number}`);
      setHistoryOpen(false);
      backToCurrent();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const compareRevision = async (rev: ArtifactRevisionInfo) => {
    if (!artifact) return;
    setHistoryOpen(false);
    setCompare({ loading: true });
    try {
      const res = await api.compareArtifactRevisions(agentId, artifact.id, rev.revision_id);
      setCompare({
        loading: false,
        comparable: res.comparable,
        diff: res.diff,
        identical: res.identical,
        reason: res.reason,
        fromN: res.from_revision_number,
        toN: res.to_revision_number,
        fromBytes: res.from_bytes,
        toBytes: res.to_bytes,
      });
    } catch (e) {
      setCompare(null);
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const download = async () => {
    try {
      const url = await be.blob(viewing);
      const a = document.createElement("a");
      a.href = url;
      a.download = payload?.name || "download";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const openFile = async () => {
    const absPath = payload?.absolute_path;
    if (!absPath || !isDesktopShell) return;
    try {
      const { openPath } = await import("@tauri-apps/plugin-opener");
      await openPath(absPath);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const revealFile = async () => {
    const absPath = payload?.absolute_path;
    if (!absPath || !isDesktopShell) return;
    try {
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(absPath);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const addToVault = async () => {
    if (!currentPath) return;
    try {
      await api.ingestWorkspaceToVault(agentId, currentPath);
      setActionMsg("Added to Vault");
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const trackHistory = async () => {
    if (!currentPath) return;
    try {
      await api.adoptWorkspaceFile(agentId, currentPath);
      setActionMsg("Now tracking revisions");
      fetchPreview();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div
      className={`flex h-full flex-col border-l border-[var(--border)] bg-[var(--white)] ${className || ""}`}
      role="complementary"
      aria-label="File preview"
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <FileText className="h-4 w-4 shrink-0 text-[var(--ink-3)]" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-[var(--ink)]">
            {payload?.name || currentPath || "Preview"}
          </p>
          <p className="truncate text-[11px] text-[var(--ink-3)]">
            {payload
              ? `${payload.kind} · ${formatBytes(payload.size)}`
              : error
                ? ""
                : "Loading…"}
            {currentPath && ` · ${currentPath}`}
          </p>
        </div>
        <button
          onClick={() => {
            setLoaded(null);
            fetchPreview();
          }}
          className="rounded-[4px] p-1 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)]"
          aria-label="Refresh preview"
          title="Refresh preview"
        >
          <RefreshCcw className="h-4 w-4" />
        </button>
        {onClose && (
          <button
            onClick={onClose}
            className="rounded-[4px] p-1 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)]"
            aria-label="Close preview"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Revision banner — never silently swaps content, just flags. */}
      {artifact?.newer_exists && (
        <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-[11px] text-[var(--ink-2)]">
          <FileClock className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">
            Viewing revision {artifact.viewing_revision_number} — revision{" "}
            {artifact.current_revision_number} is current.
          </span>
          <button
            onClick={backToCurrent}
            className="font-medium text-[var(--accent)] hover:underline"
            style={{ background: "none", border: "none", cursor: "pointer" }}
          >
            View latest
          </button>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-1 border-b border-[var(--border)] px-3 py-1.5">
        {artifact && (
          <div className="relative" ref={historyRef}>
            <ActionButton icon={History} label="History" onClick={openHistory} />
            {historyOpen && (
              <div className="absolute left-0 top-full z-20 mt-1 max-h-64 w-72 overflow-auto rounded-[5px] border border-[var(--border)] bg-[var(--white)] shadow-lg">
                {history === null ? (
                  <p className="p-3 text-[12px] text-[var(--ink-3)]">Loading…</p>
                ) : history.length === 0 ? (
                  <p className="p-3 text-[12px] text-[var(--ink-3)]">No revisions.</p>
                ) : (
                  history.map((rev) => (
                    <div
                      key={rev.revision_id}
                      className="flex items-center gap-2 border-b border-[var(--border)]/50 px-3 py-2 text-[12px] last:border-0"
                    >
                      <button
                        onClick={() => viewRevision(rev)}
                        className="flex-1 text-left"
                        style={{ background: "none", border: "none", cursor: "pointer" }}
                      >
                        <span className="font-medium text-[var(--ink)]">
                          r{rev.revision_number}
                          {rev.current && (
                            <span className="ml-1 text-[10px] text-[var(--accent)]">current</span>
                          )}
                        </span>
                        <span className="ml-2 text-[var(--ink-3)]">
                          {rev.change_summary || formatBytes(rev.byte_size)}
                        </span>
                      </button>
                      {!rev.current && (
                        <>
                          <button
                            onClick={() => compareRevision(rev)}
                            title="Compare this revision with current"
                            aria-label={`Compare r${rev.revision_number} with current`}
                            className="rounded-[3px] p-1 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--accent)]"
                          >
                            <GitCompareArrows className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => restoreRevision(rev)}
                            title="Restore this revision (creates a new revision)"
                            className="rounded-[3px] p-1 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--accent)]"
                          >
                            <RefreshCcw className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}
        <ActionButton icon={Download} label="Download" onClick={download} />
        {isDesktopShell && (
          <>
            <ActionButton icon={ExternalLink} label="Open" onClick={openFile} />
            <ActionButton icon={FolderOpen} label="Reveal" onClick={revealFile} />
          </>
        )}
        {isWorkspace && (
          <ActionButton icon={BookPlus} label="Add to Vault" onClick={addToVault} />
        )}
        {isWorkspace && !artifact && currentPath && (
          <ActionButton icon={FileClock} label="Track history" onClick={trackHistory} />
        )}
        {isWorkspace && artifact && onAskRevise && (
          <ActionButton
            icon={MessageSquarePlus}
            label="Ask agent to revise"
            onClick={() => onAskRevise(artifact)}
          />
        )}
      </div>
      {actionMsg && (
        <p className="border-b border-[var(--border)] px-3 py-1 text-[11px] text-[var(--ink-2)]">
          {actionMsg}
        </p>
      )}

      {/* Content — compare mode swaps the preview for the diff. */}
      <div className="flex-1 overflow-auto p-3">
        {compare ? (
          <div>
            <button
              onClick={() => setCompare(null)}
              className="mb-2 flex items-center gap-1.5 rounded-[4px] px-2 py-1 text-[12px] text-[var(--ink-2)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back to preview
            </button>
            {compare.loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />
              </div>
            ) : compare.comparable ? (
              <>
                <p className="mb-2 text-[11px] text-[var(--ink-3)]">
                  r{compare.fromN} → r{compare.toN}
                </p>
                <DiffBlock
                  diff={compare.diff || ""}
                  path={currentPath}
                  action={compare.identical ? "unchanged" : "modified"}
                />
              </>
            ) : (
              <div className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-3 text-[12px] text-[var(--ink-2)]">
                <p className="font-medium text-[var(--ink)]">Binary compare not supported</p>
                <p className="mt-1">
                  r{compare.fromN} ({formatBytes(compare.fromBytes ?? 0)}) → r{compare.toN} (
                  {formatBytes(compare.toBytes ?? 0)})
                  {compare.identical ? " — identical bytes" : " — bytes differ"}
                </p>
              </div>
            )}
          </div>
        ) : payload ? (
          <PreviewBody payload={payload} backend={be} source={viewing} />
        ) : error ? (
          <div className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-3 text-[12px] text-[var(--ink-2)]">
            {error}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />
          </div>
        )}
      </div>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof Download;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 rounded-[4px] px-1.5 py-1 text-[11px] text-[var(--ink-2)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)]"
      style={{ border: "none", background: "none", cursor: "pointer" }}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
