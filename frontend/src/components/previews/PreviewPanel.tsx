import { cloneElement, useCallback, useEffect, useId, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileClock,
  FileDown,
  FileText,
  FolderOpen,
  GitCompareArrows,
  History,
  Loader2,
  Maximize2,
  Minimize2,
  PencilLine,
  RefreshCcw,
  Trash2,
} from "lucide-react";
import { DiffBlock } from "@/components/DiffBlock";
import { Button } from "@/components/ui/button";
import { api, workspaceBackend, type PreviewBackend, type PreviewSource } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { ArtifactRevisionInfo, PreviewPayload } from "@/lib/types";
import { formatBytes, PreviewBody } from "./renderers";
import { OfficePreviewNotice } from "./OfficePreviewNotice";

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
  /** Workspace surfaces only — enables the Delete action; called after a
   *  successful delete so the parent can refresh its listing. */
  onDeleted?: (path: string) => void;
  /** Tracked artifacts only — receives an editable revise draft
   *  (artifact id + base revision + focus context). Never auto-submits. */
  onRevise?: (draft: string) => void;
  /** Extra classes for the outer container (sizing lives with the caller). */
  className?: string;
}

/**
 * The shared preview surface — one module serves chat, Workspace, and
 * Skills. It owns the fetch lifecycle, artifact banner/actions, and
 * delegates content to the kind renderers.
 */
export function PreviewPanel({ agentId, source, backend, onClose, onDeleted, onRevise, className }: PreviewPanelProps) {
  const { confirm } = useConfirm();
  // Workspace surface = real agentId (non-workspace surfaces pass "" per the
  // prop contract). Keying off `backend` broke when WorkspacePanel started
  // passing an explicit session-pinned backend — Track/Delete silently hid.
  const isWorkspace = agentId !== "";
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
  const [exporting, setExporting] = useState<"pptx" | "pdf" | null>(null);
  const [viewing, setViewing] = useState<PreviewSource>(source);
  // Expanded mode — the same panel floats over a backdrop for focused
  // reading; Escape collapses back to the docked panel before closing.
  const [expanded, setExpanded] = useState(false);
  // Focus context reported by the active renderer ("slide 3 of 12",
  // sheet name) — feeds the revise draft's target hint.
  const [focusLabel, setFocusLabel] = useState<string | null>(null);
  // Monotonic fetch guard — a late response/error for a previous source
  // must never paint over the source now being viewed.
  const fetchSeq = useRef(0);
  const expandBtnRef = useRef<HTMLButtonElement>(null);
  const wasExpanded = useRef(expanded);
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
    setExpanded(false);
    setFocusLabel(null);
  }, [source.path, source.artifactId, source.revisionId]);

  const fetchPreview = useCallback(async () => {
    const seq = ++fetchSeq.current;
    const key = sourceKey(viewing);
    setError(null);
    try {
      const result = await be.preview(viewing);
      if (seq === fetchSeq.current) setLoaded({ key, payload: result });
    } catch (e) {
      if (seq === fetchSeq.current) {
        setError(e instanceof Error ? e.message : String(e));
        setLoaded(null);
      }
    }
  }, [be, viewing.path, viewing.artifactId, viewing.revisionId]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  // Collapsing expanded mode (backdrop click / Escape) would drop focus
  // to <body> — return it to the toggle that owns the state.
  useEffect(() => {
    if (wasExpanded.current && !expanded) expandBtnRef.current?.focus();
    wasExpanded.current = expanded;
  }, [expanded]);

  // Escape collapses an expanded preview first, then closes the panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // The presentation player owns Escape, including its fullscreen fallback.
        if (document.querySelector("[data-deck-slideshow]")) return;
        e.stopPropagation();
        if (expanded) setExpanded(false);
        else onClose?.();
      }
    };
    // Inner controls (for example a focused tooltip) handle Escape first.
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, expanded]);

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
      const res = await api.restoreArtifactRevision(agentId, artifact.id, rev.revision_id, artifact.current_revision_id ?? undefined);
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

  const reviseDraft = () => {
    if (!artifact || !onRevise) return;
    // Base = the revision under review (viewing) or current — never a
    // silently rebased target.
    const baseRev = artifact.viewing_revision_id ?? artifact.current_revision_id;
    const lines = [
      `Please revise artifact ${artifact.id} (format ${artifact.format}) based on revision ${baseRev}.`,
      `File: ${currentPath}`,
    ];
    if (focusLabel) lines.push(`Focus: ${focusLabel}`);
    lines.push("", "Changes: ");
    onRevise(lines.join("\n"));
  };

  // Native PPTX export for .deck.json specs — pinned to the previewed
  // source hash; the backend refuses unsupported slides with a real error.
  const canExportDeck =
    payload?.kind === "deck" && !!be.exportDeckPptx && !!payload.source?.sha256;
  const exportDeck = async () => {
    const sha = payload?.source?.sha256;
    if (!payload || !canExportDeck || !sha || exporting !== null) return;
    setExporting("pptx");
    setActionMsg(null);
    const filename = `${payload.name.replace(/\.deck\.json$/i, "") || "deck"}.pptx`;
    try {
      const plan = await be.deckExportPlan?.(viewing, sha);
      if (plan?.declared_motion && !await confirm({
        title: "Static PowerPoint export",
        message: "This deck declares slide transitions or animations. They play in Slideshow but are browser-only — the PPTX exports the final static state of every slide.",
        confirmLabel: "Export static PPTX",
      })) return;
      if (plan?.image_fallbacks.length) {
        if (!be.exportDeckWithFallback || !await confirm({
          title: "Some slides need image fallback",
          message: `${plan.image_fallbacks.map(s => `Slide ${s.slide}: ${s.reason}`).join("\n")}\n\nThese slides will be images, not individually editable. Other slides remain native objects.`,
          confirmLabel: `Export with ${plan.image_fallbacks.length} image slides`,
        })) return;
        await be.exportDeckWithFallback(viewing, filename, sha, plan.plan_hash);
        return;
      }
      await be.exportDeckPptx!(viewing, filename, sha);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(null);
    }
  };
  const exportPdf = async () => {
    if (!payload?.source?.sha256 || !be.exportDeckPdf || exporting !== null) return;
    setExporting("pdf");
    setActionMsg(null);
    try {
      await be.exportDeckPdf(viewing, `${payload.name.replace(/\.deck\.json$/i, "")}.pdf`, payload.source.sha256);
    } catch (e) { setActionMsg(String(e)); }
    finally { setExporting(null); }
  };

  const trackHistory = async () => {
    if (!currentPath) return;
    try {
      await api.adoptWorkspaceFile(agentId, currentPath, viewing.sessionId);
      setActionMsg("Now tracking revisions");
      fetchPreview();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const deleteFile = async () => {
    const rel = viewing.path;
    if (!rel || !onDeleted) return;
    const ok = await confirm({
      title: "Delete file?",
      message: `Delete "${rel}"? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteWorkspaceEntry(agentId, rel, viewing.sessionId);
      onDeleted(rel);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      {/* Backdrop for expanded mode — click collapses back to docked. */}
      {expanded && (
        <div
          className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px]"
          aria-hidden="true"
          onClick={() => setExpanded(false)}
        />
      )}
      <div
        className={
          expanded
            ? "fixed inset-x-0 top-[2.5vh] bottom-[2.5vh] z-50 mx-auto flex w-[min(1240px,95vw)] flex-col overflow-hidden rounded-lg border border-line bg-ground text-ink shadow-2xl"
            : `flex h-full min-h-0 min-w-0 flex-col border-l border-line bg-ground text-ink ${className || ""}`
        }
        role="complementary"
        aria-label="File preview"
      >
      {/* Header — h-12 matches the workspace file picker's header row so
          the two divider lines align across the panel. */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface px-3">
        <FileText aria-hidden="true" className="h-4 w-4 shrink-0 text-ink-faint" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-ink">
            {payload?.name || currentPath || "Preview"}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {payload
              ? `${payload.kind} · ${formatBytes(payload.size)}`
              : error
                ? ""
                : "Loading…"}
            {currentPath && ` · ${currentPath}`}
          </p>
        </div>
        <HeaderTip
          tip={
            <span className="block">
              <span className="block font-medium text-ink">
                {payload?.name || currentPath || "Download"}
              </span>
              <span className="block text-ink-muted">
                {payload ? `${payload.kind} · ${formatBytes(payload.size)}` : ""}
                {currentPath ? `${payload ? " · " : ""}${currentPath}` : ""}
              </span>
            </span>
          }
        >
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={download}
            className="text-ink-muted"
            aria-label="Download file"
          >
            <Download className="h-4 w-4" />
          </Button>
        </HeaderTip>
        <HeaderTip tip="Reload the latest file contents">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              setLoaded(null);
              fetchPreview();
            }}
            className="text-ink-muted"
            aria-label="Refresh preview"
          >
            <RefreshCcw className="h-4 w-4" />
          </Button>
        </HeaderTip>
        <HeaderTip tip={expanded ? "Restore panel size" : "Expand preview to a larger view"}>
          <Button
            variant="ghost"
            size="icon-sm"
            ref={expandBtnRef}
            onClick={() => setExpanded((v) => !v)}
            className="text-ink-muted"
            aria-label={expanded ? "Restore panel size" : "Expand preview"}
          >
            {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        </HeaderTip>
        {/* No close button — Workspace's panel ✕ / Skills' "← files"
            back button / Escape already cover dismissal; one less
            header control. onClose still drives the Escape path. */}
      </div>

      {/* Moved-file notice — the requested path no longer exists; the
          panel resolved a unique basename match and says so. */}
      {payload?.moved_from && (
        <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface px-3 py-2 text-xs text-ink-muted">
          <FileClock className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">
            This file was moved or renamed — showing <span className="font-mono">{payload.path}</span>.
          </span>
        </div>
      )}

      {/* Revision banner — never silently swaps content, just flags. */}
      {artifact?.newer_exists && (
        <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface px-3 py-2 text-xs text-ink-muted">
          <FileClock className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">
            Viewing revision {artifact.viewing_revision_number} — revision{" "}
            {artifact.current_revision_number} is current.
          </span>
          <Button
            variant="link"
            size="xs"
            onClick={backToCurrent}
            className="px-0"
          >
            View latest
          </Button>
        </div>
      )}

      {/* Actions — artifact history/revise plus secondary actions (desktop
          open/reveal, track history, delete). Renders only when at least
          one action exists so plain previews don't show an empty strip. */}
      {(artifact ||
        canExportDeck ||
        isDesktopShell ||
        (isWorkspace && !artifact && currentPath) ||
        (isWorkspace && viewing.path && onDeleted)) && (
        <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-line bg-surface px-3 py-2">
          {artifact && (
            <div className="relative" ref={historyRef}>
              <ActionButton icon={History} label="History" onClick={openHistory} />
              {historyOpen && (
                <div className="absolute left-0 top-full z-20 mt-1 max-h-64 w-64 max-w-[calc(100vw-3rem)] overflow-auto rounded-md border border-line bg-surface p-1 shadow-lg">
                  {history === null ? (
                    <p className="p-3 text-xs text-ink-muted">Loading…</p>
                  ) : history.length === 0 ? (
                    <p className="p-3 text-xs text-ink-muted">No revisions.</p>
                  ) : (
                    history.map((rev) => (
                      <div
                        key={rev.revision_id}
                        className="flex items-center gap-1 border-b border-line px-1 py-1 text-xs last:border-0"
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => viewRevision(rev)}
                          className="h-auto min-h-8 min-w-0 flex-1 justify-start whitespace-normal px-1.5 py-1.5 text-left text-xs font-normal"
                        >
                          <span className="shrink-0 font-medium text-ink">
                            r{rev.revision_number}
                            {rev.current && (
                              <span className="ml-1 text-xs text-accent">current</span>
                            )}
                          </span>
                          <span className="min-w-0 break-words text-ink-muted">
                            {rev.change_summary || formatBytes(rev.byte_size)}
                          </span>
                        </Button>
                        {!rev.current && (
                          <>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => compareRevision(rev)}
                              title="Compare this revision with current"
                              aria-label={`Compare r${rev.revision_number} with current`}
                              className="text-ink-muted hover:text-accent"
                            >
                              <GitCompareArrows className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => restoreRevision(rev)}
                              title="Restore this revision (creates a new revision)"
                              aria-label={`Restore r${rev.revision_number}`}
                              className="text-ink-muted hover:text-accent"
                            >
                              <RefreshCcw className="h-3.5 w-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
          {artifact && onRevise && (
            <ActionButton icon={PencilLine} label="Revise" onClick={reviseDraft} />
          )}
          {canExportDeck && (
            <ActionButton
              icon={FileDown}
              label={exporting === "pptx" ? "Exporting…" : "Export PPTX"}
              onClick={exportDeck}
              disabled={exporting !== null}
            />
          )}
          {payload?.kind === "deck" && be.exportDeckPdf && (
            <ActionButton icon={FileDown} label={exporting === "pdf" ? "Exporting…" : "Export PDF"} onClick={exportPdf} disabled={exporting !== null} />
          )}
          {isDesktopShell && (
            <>
              <ActionButton icon={ExternalLink} label="Open" onClick={openFile} />
              <ActionButton icon={FolderOpen} label="Reveal" onClick={revealFile} />
            </>
          )}
          {isWorkspace && !artifact && currentPath && (
            <ActionButton icon={FileClock} label="Track history" onClick={trackHistory} />
          )}
          {isWorkspace && viewing.path && onDeleted && (
            <ActionButton icon={Trash2} label="Delete" onClick={deleteFile} />
          )}
        </div>
      )}
      {actionMsg && (
        <p role="status" className="shrink-0 border-b border-line bg-surface px-3 py-2 text-xs text-ink-muted">
          {actionMsg}
        </p>
      )}
      {payload?.kind === "deck" && payload.spec && (
        <p className="shrink-0 border-b border-line bg-surface px-3 py-2 text-xs text-ink-muted">
          Motion plays in Slideshow. PPTX export shows all content without animations.
        </p>
      )}

      {payload && !compare && !payload.error && (
        <OfficePreviewNotice kind={payload.kind} mode={payload.mode} />
      )}

      {/* Content — compare mode swaps the preview for the diff. In expanded
          mode each kind gets its own framing: visual kinds center on both
          axes (auto margins clamp to top-align + scroll when taller), wide
          kinds get a wider column, text kinds a readable column. */}
      <div
        className={`${payload && ["deck", "html"].includes(payload.kind) && !compare ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "flex-1 overflow-auto"} ${
          expanded
            ? payload && !compare && ["image", "pdf", "media"].includes(payload.kind)
              ? "flex flex-col"
              : ""
            : "p-3"
        }`}
      >
        <div
          className={
            payload && ["deck", "html"].includes(payload.kind) && !compare
              ? "min-h-0 flex-1"
              : !expanded
                ? ""
                : payload && !compare && ["image", "pdf", "media"].includes(payload.kind)
                  ? "m-auto w-fit max-w-full p-6"
                  : `mx-auto w-full p-6 ${
                      compare || (payload && ["table", "workbook", "slides"].includes(payload.kind))
                        ? "max-w-[1000px]"
                        : "max-w-[840px]"
                    }`
          }
        >
        {compare ? (
          <div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCompare(null)}
              className="mb-2 text-ink-muted"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back to preview
            </Button>
            {compare.loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-ink-faint" />
              </div>
            ) : compare.comparable ? (
              <>
                <p className="mb-2 text-xs text-ink-muted">
                  r{compare.fromN} → r{compare.toN}
                </p>
                <DiffBlock
                  diff={compare.diff || ""}
                  path={currentPath}
                  action={compare.identical ? "unchanged" : "modified"}
                />
              </>
            ) : (
              <div className="rounded-md border border-line bg-surface p-3 text-xs text-ink-muted">
                <p className="font-medium text-ink">Binary compare not supported</p>
                <p className="mt-1">
                  r{compare.fromN} ({formatBytes(compare.fromBytes ?? 0)}) → r{compare.toN} (
                  {formatBytes(compare.toBytes ?? 0)})
                  {compare.identical ? " — identical bytes" : " — bytes differ"}
                </p>
              </div>
            )}
          </div>
        ) : payload ? (
          <PreviewBody
            payload={payload}
            backend={be}
            source={viewing}
            expanded={expanded}
            onFocus={setFocusLabel}
          />
        ) : error ? (
          <div className="rounded-md border border-line bg-surface p-3 text-xs text-ink-muted">
            {/^404\b/.test(error) ? (
              <>
                <p className="font-medium text-ink">File not found</p>
                <p className="mt-1">It may have been moved or deleted from the workspace.</p>
              </>
            ) : (
              error
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-ink-faint" />
          </div>
        )}
        </div>
      </div>
      </div>
    </>
  );
}

/** Header descriptions are available on both hover and keyboard focus. */
function HeaderTip({ tip, children }: {
  tip: ReactNode;
  children: ReactElement<{ "aria-describedby"?: string }>;
}) {
  const [hover, setHover] = useState(false);
  const tipId = useId();
  return (
    <span
      className="relative inline-flex shrink-0"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && hover) {
          event.stopPropagation();
          setHover(false);
        }
      }}
    >
      {cloneElement(children, { "aria-describedby": hover ? tipId : undefined })}
      {hover && (
        <span id={tipId} role="tooltip" className="absolute right-0 top-full z-50 mt-2 block w-max max-w-[min(18rem,calc(100vw-3rem))] rounded-md border border-line bg-surface px-3 py-2 text-left text-xs leading-relaxed text-ink-muted shadow-lg [overflow-wrap:anywhere]">
          {tip}
        </span>
      )}
    </span>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: typeof Download;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button
      variant="ghost"
      size="xs"
      disabled={disabled}
      onClick={onClick}
      className="text-ink-muted"
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </Button>
  );
}
