import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, ChevronRight, ChevronDown, File, Folder, FolderOpen,
  Sparkles, Upload, Trash2, FileText,
  Search, Package, Plus, Globe, Download, History, Archive,
  Ban, RotateCcw, Link2, X,
} from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/PageHeader";
import { api, skillBackend } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { useResizableWidth } from "@/lib/useResizableWidth";
import type {
  Agent, SkillCandidate, SkillDetail, SkillInfo, SkillScope,
} from "@/lib/types";
import { PreviewPanel } from "@/components/previews/PreviewPanel";
import { formatBytes } from "@/components/previews/renderers";
import { Markdown } from "@/components/Markdown";

type ViewKey = "all" | "built-in" | "global" | "agent-local" | "drafts" | "archived";
type DetailTab = "overview" | "instructions" | "resources" | "history" | "usage";

const VIEWS: { key: ViewKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "built-in", label: "Built-in" },
  { key: "global", label: "Global" },
  { key: "agent-local", label: "Agent Skills" },
  { key: "drafts", label: "Drafts" },
  { key: "archived", label: "Archived" },
];

const SCOPE_STYLE: Record<SkillScope, { label: string; color: string }> = {
  "built-in": { label: "built-in", color: "#6b7280" },
  global: { label: "global", color: "#2563eb" },
  "agent-local": { label: "agent", color: "#7c3aed" },
};

const STATUS_STYLE: Record<string, string> = {
  published: "var(--success)",
  draft: "var(--warning)",
  disabled: "var(--ink-2)",
  archived: "var(--ink-3)",
};

const MAIN_MIN_WIDTH = 420;

export function Skills() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewKey>("all");
  const [agentFilter, setAgentFilter] = useState<string>("");

  // Detail drawer
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [files, setFiles] = useState<{ path: string; size: number; mime: string }[] | null>(null);
  const [filesRevision, setFilesRevision] = useState<number | undefined>(undefined);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const {
    width: drawerWidth,
    dragging: drawerDragging,
    startResize: startDrawerResize,
  } = useResizableWidth({ initial: 560, min: 380, max: 1100, storageKey: "caberos.skillDrawer.width" });

  // Content region (main pane + drawer) — measured independently of the
  // docked drawer so there's no feedback loop.
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentWidth, setContentWidth] = useState(0);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      setContentWidth(entries[0].contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const drawerOverlay = contentWidth > 0 && contentWidth - drawerWidth < MAIN_MIN_WIDTH;

  // Dialogs
  const [showCreate, setShowCreate] = useState(false);
  const [showImportUrl, setShowImportUrl] = useState(false);
  const [publishTarget, setPublishTarget] = useState<SkillDetail | null>(null);
  const [candidates, setCandidates] = useState<SkillCandidate[] | null>(null);
  const [pendingImport, setPendingImport] = useState<
    { kind: "zip"; file: File } | { kind: "url"; url: string } | null
  >(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { confirm } = useConfirm();

  const previewBackend = useMemo(
    () =>
      detail
        ? skillBackend(detail.id, filesRevision)
        : null,
    [detail, filesRevision],
  );

  const loadSeq = useRef(0);

  const loadSkills = useCallback(async () => {
    const seq = ++loadSeq.current;
    try {
      setLoading(true);
      const data = await api.listSkills(
        view,
        view === "agent-local" && agentFilter ? agentFilter : undefined,
        search || undefined,
      );
      if (seq !== loadSeq.current) return;
      setSkills(data.skills);
      setError(null);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setError(e instanceof Error ? e.message : "Failed to load skills");
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [view, agentFilter, search]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
  }, []);

  const openDetail = async (id: string, tab: DetailTab = "overview") => {
    setSelectedId(id);
    setDetailTab(tab);
    setPreviewPath(null);
    setFilesRevision(undefined);
    try {
      setDetail(await api.skillDetail(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load skill");
    }
  };

  const closeDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setFiles(null);
    setPreviewPath(null);
    setFilesRevision(undefined);
  };

  const refreshDetail = async () => {
    if (!selectedId) return;
    try {
      setDetail(await api.skillDetail(selectedId));
    } catch {
      /* detail gone */
    }
    await loadSkills();
  };

  const loadFiles = async (revision?: number) => {
    if (!selectedId) return;
    setFilesRevision(revision);
    try {
      const data = await api.skillFiles(selectedId, revision);
      setFiles(data.files);
    } catch {
      setFiles([]);
    }
  };

  useEffect(() => {
    if (detailTab === "resources" && detail && files === null) loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailTab, detail]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    const routes: Record<string, string> = {
      agents: "/agents", settings: "/settings", vault: "/vault",
      scheduler: "/scheduler", mcps: "/mcps", channels: "/channels",
      observability: "/observability", traces: "/traces",
    };
    if (page !== "skills" && routes[page]) navigate(routes[page]);
  };

  // --- imports ---

  const handleImportResult = async (result: {
    imported?: { id: string; name: string }[];
    errors?: string[];
    candidates?: SkillCandidate[];
  }) => {
    if (result.candidates?.length && !result.imported?.length) {
      setCandidates(result.candidates);
      return;
    }
    const errs = result.errors?.length ? ` — issues: ${result.errors.join("; ")}` : "";
    setNotice(
      `Imported ${result.imported?.length ?? 0} draft(s)` +
        (result.imported?.length
          ? `: ${result.imported.map((i) => i.name).join(", ")}`
          : "") +
        errs,
    );
    if (view === "drafts") {
      await loadSkills();
    } else {
      setView("drafts");
    }
  };

  const handleZipImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setPendingImport({ kind: "zip", file });
      await handleImportResult(await api.importSkillZip(file));
    } catch (err) {
      setError(`Import failed: ${err instanceof Error ? err.message : "unknown"}`);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleCandidateImport = async (paths: string[]) => {
    if (!pendingImport) return;
    try {
      const result =
        pendingImport.kind === "zip"
          ? await api.importSkillZip(pendingImport.file, { paths })
          : await api.importSkillUrl({ url: pendingImport.url, paths });
      setCandidates(null);
      setPendingImport(null);
      await handleImportResult(result);
    } catch (err) {
      setError(`Import failed: ${err instanceof Error ? err.message : "unknown"}`);
    }
  };

  // --- actions ---

  const handleDelete = async (skill: SkillInfo) => {
    const isDraft = skill.status === "draft";
    const ok = await confirm({
      title: isDraft ? "Delete draft?" : "Purge skill?",
      message: isDraft
        ? `Delete draft "${skill.name}"?`
        : `Purge "${skill.name}"? Requires archived/disabled status and no active runs pinning it. This deletes stored revisions.`,
      confirmLabel: isDraft ? "Delete" : "Purge",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteSkill(skill.id);
      if (selectedId === skill.id) closeDetail();
      await loadSkills();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const handleStatus = async (skill: SkillInfo, status: "published" | "disabled" | "archived") => {
    try {
      await api.setSkillStatus(skill.id, status);
      await refreshDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Status change failed");
    }
  };

  const handleExport = async (skill: SkillInfo) => {
    try {
      const url = await api.exportSkill(skill.id);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${skill.name}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
  };

  const handleRestore = async (skill: SkillInfo, revision: number) => {
    try {
      await api.restoreSkill(skill.id, revision);
      await refreshDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Restore failed");
    }
  };

  const scopeBadge = (s: SkillInfo) => {
    const st = SCOPE_STYLE[s.scope] ?? SCOPE_STYLE["built-in"];
    return (
      <span
        className="rounded px-1.5 py-0.5 text-[11px] font-medium"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", color: st.color }}
      >
        {st.label}
        {s.scope === "agent-local" && s.owner_name ? ` · ${s.owner_name}` : ""}
      </span>
    );
  };

  const statusBadge = (s: SkillInfo) =>
    s.status !== "published" ? (
      <span
        className="rounded px-1.5 py-0.5 text-[11px] font-medium"
        style={{ color: STATUS_STYLE[s.status] ?? "var(--ink-3)", border: `1px solid color-mix(in srgb, ${STATUS_STYLE[s.status] ?? "var(--ink-3)"} 30%, transparent)` }}
      >
        {s.status}
      </span>
    ) : null;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="skills"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div ref={contentRef} className="relative flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <PageHeader
          icon={Sparkles}
          title="Skills"
          description={`${skills.length} skill${skills.length !== 1 ? "s" : ""} · versioned, scoped library`}
        >
          <div className="ml-auto flex items-center gap-2">
            <input ref={fileInputRef} type="file" accept=".zip" onChange={handleZipImport} style={{ display: "none" }} />
            <button onClick={() => setShowImportUrl(true)} style={btn("secondary")}>
              <Link2 className="h-4 w-4" /> From URL
            </button>
            <button onClick={() => fileInputRef.current?.click()} style={btn("secondary")}>
              <Upload className="h-4 w-4" /> Import .zip
            </button>
            <button onClick={() => setShowCreate(true)} style={btn("primary")}>
              <Plus className="h-4 w-4" /> Create Skill
            </button>
          </div>
        </PageHeader>

        {notice && (
          <div className="mx-8 mt-4 rounded-lg px-4 py-3 text-[13px]" style={{ background: "color-mix(in srgb, var(--success) 10%, transparent)", color: "var(--success)" }}>
            {notice}
            <button onClick={() => setNotice(null)} style={{ float: "right", background: "none", border: "none", cursor: "pointer", color: "inherit" }}><X className="h-3.5 w-3.5" /></button>
          </div>
        )}
        {error && (
          <div className="mx-8 mt-4 rounded-lg px-4 py-3 text-[13px]" style={{ background: "color-mix(in srgb, var(--danger) 10%, transparent)", color: "var(--danger)" }}>
            {error}
            <button onClick={() => setError(null)} style={{ float: "right", background: "none", border: "none", cursor: "pointer", color: "inherit" }}><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        {/* View tabs + search + agent filter */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-8 py-4">
          <div className="flex shrink-0 gap-1 rounded-lg p-1" style={{ background: "var(--sidebar)", border: "1px solid var(--border-soft)" }}>
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => setView(v.key)}
                className="whitespace-nowrap rounded-[6px] px-3 py-1.5 text-[12px] font-medium transition"
                style={{
                  background: view === v.key ? "var(--accent)" : "transparent",
                  color: view === v.key ? "var(--white)" : "var(--ink-3)",
                  border: "none",
                  cursor: "pointer",
                  boxShadow: view === v.key ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
                }}
              >
                {v.label}
              </button>
            ))}
          </div>
          <div className="relative min-w-[160px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: "var(--ink-3)" }} />
            <input
              type="text" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search skills..."
              className="w-full rounded-lg py-2 pl-10 pr-4 text-[13px]"
              style={{ background: "var(--surface)", border: "1px solid var(--ink-3)", color: "var(--ink)" }}
            />
          </div>
          {view === "agent-local" && (
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--surface)", border: "1px solid var(--ink-3)", color: "var(--ink)" }}
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          )}
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto px-8 pb-8">
          {loading ? (
            <p className="py-20 text-center text-[14px] text-[var(--ink-3)]">Loading skills...</p>
          ) : skills.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20">
              <Package className="h-12 w-12 mb-3" style={{ color: "var(--ink-3)" }} />
              <p className="text-[14px] text-[var(--ink-3)]">
                {view === "drafts" ? "No drafts" : "No skills in this view"}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-4">
              {skills.map((skill) => (
                <div
                  key={skill.id}
                  className="group cursor-pointer rounded-xl p-5 transition-shadow hover:shadow-md"
                  style={{ background: "var(--sidebar)", border: "1px solid var(--border-soft)" }}
                  onClick={() => openDetail(skill.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <Sparkles className="h-5 w-5 shrink-0" style={{ color: "var(--accent)" }} />
                      <h3 className="truncate text-[14px] font-semibold text-[var(--ink)]">{skill.name}</h3>
                    </div>
                    {(skill.status === "draft" ||
                      (skill.scope !== "built-in" && skill.status !== "published")) && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(skill); }}
                        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded border-0 bg-transparent text-[var(--ink-3)] opacity-0 transition group-hover:opacity-100 hover:bg-[var(--border)] hover:text-[var(--ink)]"
                        title={skill.status === "draft" ? "Delete draft" : "Purge skill"}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>

                  <p className="mt-2 text-[13px] leading-relaxed line-clamp-2" style={{ color: "var(--ink-2)" }}>
                    {skill.description || "No description"}
                  </p>

                  <div className="mt-4 flex flex-wrap items-center gap-2 text-[12px]" style={{ color: "var(--ink-3)" }}>
                    {scopeBadge(skill)}
                    {statusBadge(skill)}
                    {skill.current_revision != null && (
                      <span className="rounded px-1.5 py-0.5" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                        rev {skill.current_revision}
                      </span>
                    )}
                    <span className="flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      {skill.resource_count}
                    </span>
                    {skill.scope === "global" && skill.availability === "selected" && (
                      <span title={skill.assigned_names.join(", ")} className="flex items-center gap-1">
                        <Globe className="h-3 w-3" /> {skill.assigned_names.length} agent{skill.assigned_names.length !== 1 ? "s" : ""}
                      </span>
                    )}
                    {skill.builder_session_id && (
                      <span style={{ color: "var(--accent)" }} title="Builder session active">building…</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Detail drawer — docked when the main pane keeps room, overlay when not */}
      {detail && (
        <div
          className={
            drawerOverlay
              ? "absolute inset-y-0 right-0 z-30 flex flex-col border-l border-[var(--border)] bg-[var(--surface)] shadow-xl"
              : "relative flex shrink-0 flex-col border-l border-[var(--border)] bg-[var(--surface)]"
          }
          style={{
            width: drawerOverlay
              ? Math.min(drawerWidth, contentWidth)
              : `min(100%, ${drawerWidth}px)`,
          }}
        >
          <div
            onMouseDown={startDrawerResize}
            className={`absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize transition-colors hover:bg-[var(--accent)]/40 ${drawerDragging ? "bg-[var(--accent)]/40" : ""}`}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize detail panel"
          />
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-[14px] font-semibold text-[var(--ink)]">{detail.name}</p>
              <p className="text-[11px] text-[var(--ink-3)]">
                {detail.scope}
                {detail.owner_name ? ` · ${detail.owner_name}` : ""}
                {detail.current_revision != null ? ` · rev ${detail.current_revision}` : ""}
                {detail.status !== "published" ? ` · ${detail.status}` : ""}
              </p>
            </div>
            <button onClick={closeDetail} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-3)" }}>
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Tab bar */}
          <div className="flex gap-1 overflow-x-auto border-b border-[var(--border)] px-3 py-2">
            {(["overview", "instructions", "resources", "history", "usage"] as DetailTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setDetailTab(t)}
                className="shrink-0 whitespace-nowrap rounded-[6px] px-2.5 py-1 text-[12px] font-medium capitalize"
                style={{
                  background: detailTab === t ? "var(--sidebar)" : "transparent",
                  color: detailTab === t ? "var(--ink)" : "var(--ink-3)",
                  border: "none", cursor: "pointer",
                }}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {detailTab === "overview" && (
              <OverviewTab
                detail={detail}
                onPublish={() => setPublishTarget(detail)}
                onExport={() => handleExport(detail)}
                onStatus={(s) => handleStatus(detail, s)}
                onDelete={() => handleDelete(detail)}
                onResumeBuilder={() =>
                  detail.builder_session_id &&
                  navigate(`/agents/${detail.owner_agent_id}/chat?session=${detail.builder_session_id}`)
                }
              />
            )}
            {detailTab === "instructions" && (
              <div className="markdown-body p-4 text-[13px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                {detail.body ? <Markdown>{detail.body}</Markdown> : <p className="text-[var(--ink-3)]">No instructions body.</p>}
              </div>
            )}
            {detailTab === "resources" && (
              <div>
                <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2">
                  {detail.revisions.length > 0 && (
                    <select
                      value={filesRevision ?? detail.current_revision ?? ""}
                      onChange={(e) => loadFiles(e.target.value ? Number(e.target.value) : undefined)}
                      className="rounded px-2 py-1 text-[12px]"
                      style={{ background: "var(--sidebar)", border: "1px solid var(--border)", color: "var(--ink)" }}
                    >
                      <option value="">
                        {detail.scope === "agent-local" ? "live copy" : "current"}
                      </option>
                      {detail.revisions.map((r) => (
                        <option key={r.revision_number} value={r.revision_number}>
                          rev {r.revision_number}
                        </option>
                      ))}
                    </select>
                  )}
                  <span className="text-[11px] text-[var(--ink-3)]">{files?.length ?? "…"} files</span>
                </div>
                {previewPath && previewBackend ? (
                  <div className="flex h-[70vh] flex-col">
                    <button
                      onClick={() => setPreviewPath(null)}
                      className="flex items-center gap-1.5 border-b border-[var(--border)] px-3 py-2 text-[12px] text-[var(--ink-2)] hover:bg-[var(--sidebar)]"
                      style={{ background: "none", cursor: "pointer", border: "none", borderBottom: "1px solid var(--border)" }}
                    >
                      <ArrowLeft className="h-3.5 w-3.5" /> files
                    </button>
                    <div className="min-h-0 flex-1">
                      <PreviewPanel agentId="" backend={previewBackend} source={{ path: previewPath }} onClose={() => setPreviewPath(null)} />
                    </div>
                  </div>
                ) : (
                  <FileTree files={files ?? []} onOpen={setPreviewPath} />
                )}
              </div>
            )}
            {detailTab === "history" && (
              <HistoryTab detail={detail} onRestore={handleRestore} />
            )}
            {detailTab === "usage" && (
              <div className="p-4">
                {detail.usage.length === 0 ? (
                  <p className="text-[12px] text-[var(--ink-3)]">No runs have pinned this skill yet.</p>
                ) : (
                  detail.usage.map((u) => (
                    <div key={u.run_id} className="flex items-center justify-between border-b border-[var(--border)]/50 py-2 text-[12px]">
                      <span className="font-mono text-[var(--ink)]">{u.run_id.slice(0, 8)}…</span>
                      <span className="text-[var(--ink-3)]">{u.status}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}
      </div>

      {/* Dialogs */}
      {showCreate && (
        <CreateDialog
          agents={agents}
          onClose={() => setShowCreate(false)}
          onCreated={async (sessionId, agentId) => {
            setShowCreate(false);
            await loadSkills();
            if (sessionId && agentId) navigate(`/agents/${agentId}/chat?session=${sessionId}`);
          }}
        />
      )}
      {showImportUrl && (
        <ImportUrlDialog
          onClose={() => setShowImportUrl(false)}
          onSubmit={async (url) => {
            try {
              setPendingImport({ kind: "url", url });
              const result = await api.importSkillUrl({ url });
              setShowImportUrl(false);
              await handleImportResult(result);
            } catch (e) {
              setShowImportUrl(false);
              setError(`Import failed: ${e instanceof Error ? e.message : "unknown"}`);
            }
          }}
        />
      )}
      {publishTarget && (
        <PublishDialog
          skill={publishTarget}
          agents={agents}
          onClose={() => setPublishTarget(null)}
          onPublished={async () => {
            setPublishTarget(null);
            await refreshDetail();
          }}
        />
      )}
      {candidates && (
        <CandidatePicker
          candidates={candidates}
          onCancel={() => { setCandidates(null); setPendingImport(null); }}
          onImport={handleCandidateImport}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function btn(kind: "primary" | "secondary" | "danger"): React.CSSProperties {
  const base: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 6, borderRadius: 6,
    padding: "8px 12px", fontSize: 13, fontWeight: 500, cursor: "pointer",
  };
  if (kind === "primary")
    return { ...base, background: "var(--ink)", color: "var(--white)", border: "1px solid var(--ink)" };
  if (kind === "danger")
    return { ...base, background: "transparent", color: "var(--danger)", border: "1px solid color-mix(in srgb, var(--danger) 40%, transparent)" };
  return { ...base, background: "transparent", color: "var(--ink)", border: "1px solid var(--border)" };
}

function OverviewTab({
  detail, onPublish, onExport, onStatus, onDelete, onResumeBuilder,
}: {
  detail: SkillDetail;
  onPublish: () => void;
  onExport: () => void;
  onStatus: (s: "published" | "disabled" | "archived") => void;
  onDelete: () => void;
  onResumeBuilder: () => void;
}) {
  const v = detail.validation;
  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">Description</p>
        <p className="text-[13px] text-[var(--ink)]">{detail.description || "—"}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-[12px]">
        <Field label="Scope" value={detail.scope + (detail.owner_name ? ` (${detail.owner_name})` : "")} />
        <Field label="Status" value={detail.status} />
        <Field label="Revision" value={detail.current_revision != null ? `#${detail.current_revision}` : "—"} />
        <Field label="Availability" value={detail.scope === "global" ? detail.availability : "—"} />
        {detail.availability === "selected" && (
          <Field label="Assigned" value={detail.assigned_names.join(", ") || "none"} />
        )}
        {detail.allowed_tools && <Field label="allowed-tools" value={detail.allowed_tools} />}
        {detail.license && <Field label="License" value={detail.license} />}
        {detail.compatibility && <Field label="Compatibility" value={detail.compatibility} />}
      </div>

      {/* Validation */}
      <div>
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">Validation</p>
        {v.errors.length === 0 && v.warnings.length === 0 ? (
          <p className="text-[12px] text-[var(--success)]">valid</p>
        ) : (
          <div className="flex flex-col gap-1">
            {v.errors.map((e) => (
              <p key={e} className="rounded px-2 py-1 text-[12px]" style={{ background: "color-mix(in srgb, var(--danger) 8%, transparent)", color: "var(--danger)" }}>error: {e}</p>
            ))}
            {v.warnings.map((w) => (
              <p key={w} className="rounded px-2 py-1 text-[12px]" style={{ background: "color-mix(in srgb, var(--warning) 8%, transparent)", color: "var(--warning)" }}>warn: {w}</p>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-4">
        {detail.status === "draft" && (
          <button onClick={onPublish} style={btn("primary")} disabled={v.errors.length > 0}
            title={v.errors.length ? "Fix validation errors first" : "Publish"}>
            Publish
          </button>
        )}
        {detail.status === "published" && detail.scope === "agent-local" && (
          <button onClick={onPublish} style={btn("secondary")}><Globe className="h-4 w-4" /> Promote to global</button>
        )}
        {detail.status !== "draft" && (
          <>
            <button onClick={onExport} style={btn("secondary")}><Download className="h-4 w-4" /> Export</button>
            {detail.status === "published" && (
              <button onClick={() => onStatus("disabled")} style={btn("secondary")}><Ban className="h-4 w-4" /> Disable</button>
            )}
            {detail.status === "disabled" && (
              <button onClick={() => onStatus("published")} style={btn("secondary")}><RotateCcw className="h-4 w-4" /> Re-enable</button>
            )}
            {detail.status !== "archived" && (
              <button onClick={() => onStatus("archived")} style={btn("secondary")}><Archive className="h-4 w-4" /> Archive</button>
            )}
            {detail.status === "archived" && detail.scope !== "built-in" && (
              <button onClick={onDelete} style={btn("danger")}><Trash2 className="h-4 w-4" /> Purge</button>
            )}
          </>
        )}
        {detail.status === "draft" && (
          <button onClick={onDelete} style={btn("danger")}><Trash2 className="h-4 w-4" /> Delete draft</button>
        )}
        {detail.builder_session_id && (
          <button onClick={onResumeBuilder} style={btn("secondary")}>
            <Sparkles className="h-4 w-4" /> Resume builder
          </button>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-[var(--ink-3)]">{label}</p>
      <p className="text-[12px] text-[var(--ink)]">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// File tree — builds a parent/child hierarchy from flat "a/b/c.txt" paths
// ---------------------------------------------------------------------------

interface FileEntry {
  path: string;
  size: number;
  mime: string;
}

interface TreeNode {
  name: string;
  /** Directory children keyed by name; files keyed by name. */
  dirs: Map<string, TreeNode>;
  files: FileEntry[];
}

function buildTree(files: FileEntry[]): TreeNode {
  const root: TreeNode = { name: "", dirs: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      let child = node.dirs.get(part);
      if (!child) {
        child = { name: part, dirs: new Map(), files: [] };
        node.dirs.set(part, child);
      }
      node = child;
    }
    node.files.push({ ...f, path: f.path });
  }
  return root;
}

function FileTree({ files, onOpen }: { files: FileEntry[]; onOpen: (path: string) => void }) {
  const tree = useMemo(() => buildTree(files), [files]);
  if (!files.length)
    return <p className="p-4 text-[12px] text-[var(--ink-3)]">No resource files.</p>;
  return (
    <div className="py-1">
      <TreeLevel node={tree} prefix="" depth={0} onOpen={onOpen} />
    </div>
  );
}

function TreeLevel({
  node, prefix, depth, onOpen,
}: {
  node: TreeNode;
  prefix: string;
  depth: number;
  onOpen: (path: string) => void;
}) {
  const dirs = [...node.dirs.values()].sort((a, b) => a.name.localeCompare(b.name));
  const fileList = [...node.files].sort((a, b) => a.path.localeCompare(b.path));
  return (
    <>
      {dirs.map((d) => (
        <TreeDir
          key={`${prefix}${d.name}/`}
          node={d}
          path={`${prefix}${d.name}`}
          depth={depth}
          onOpen={onOpen}
        />
      ))}
      {fileList.map((f) => (
        <button
          key={f.path}
          onClick={() => onOpen(f.path)}
          className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-4 py-1.5 text-left transition hover:bg-[var(--sidebar)]"
          style={{ paddingLeft: `${depth * 16 + 26}px` }}
        >
          <File className="h-3.5 w-3.5 shrink-0 text-[var(--ink-3)]" />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-mono text-[12px] text-[var(--ink)]">
              {f.path.split("/").pop()}
            </span>
          </span>
          <span className="shrink-0 text-[10px] text-[var(--ink-3)]">{formatBytes(f.size)}</span>
        </button>
      ))}
    </>
  );
}

function TreeDir({
  node, path, depth, onOpen,
}: {
  node: TreeNode;
  path: string;
  depth: number;
  onOpen: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const Chevron = open ? ChevronDown : ChevronRight;
  const FolderIcon = open ? FolderOpen : Folder;
  const count = node.files.length + [...node.dirs.values()].length;
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-4 py-1.5 text-left transition hover:bg-[var(--sidebar)]"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <Chevron className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
        <FolderIcon className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--accent)" }} />
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-[var(--ink)]">
          {node.name}
        </span>
        <span className="shrink-0 text-[10px] text-[var(--ink-3)]">{count}</span>
      </button>
      {open && (
        <TreeLevel node={node} prefix={`${path}/`} depth={depth + 1} onOpen={onOpen} />
      )}
    </div>
  );
}

function HistoryTab({
  detail, onRestore,
}: {
  detail: SkillDetail;
  onRestore: (skill: SkillInfo, rev: number) => void;
}) {
  if (!detail.revisions.length)
    return <p className="p-4 text-[12px] text-[var(--ink-3)]">No revisions yet — publish creates the first.</p>;
  return (
    <div>
      {detail.revisions.map((r) => (
        <div key={r.id} className="flex items-center justify-between border-b border-[var(--border)]/50 px-4 py-3">
          <div className="min-w-0">
            <p className="text-[12px] font-medium text-[var(--ink)]">
              rev {r.revision_number}
              {r.is_current && <span className="ml-2 rounded px-1.5 py-0.5 text-[10px]" style={{ background: "color-mix(in srgb, var(--success) 10%, transparent)", color: "var(--success)" }}>current</span>}
            </p>
            <p className="truncate text-[11px] text-[var(--ink-3)]">
              {r.change_summary || "—"} · {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
            </p>
            <p className="font-mono text-[10px] text-[var(--ink-3)]">{r.content_hash.slice(0, 12)}</p>
          </div>
          {!r.is_current && (
            <button onClick={() => onRestore(detail, r.revision_number)} style={btn("secondary")}>
              <History className="h-3.5 w-3.5" /> Restore
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function CreateDialog({
  agents, onClose, onCreated,
}: {
  agents: Agent[];
  onClose: () => void;
  onCreated: (sessionId: string | null, agentId: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [launch, setLaunch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const result = await api.createSkillDraft({
        name: name.trim(),
        agent_id: agentId || undefined,
        launch_session: launch && !!agentId,
      });
      onCreated(result.session_id, agentId || null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
      setBusy(false);
    }
  };

  return (
    <Dialog title="Create Skill" onClose={onClose}>
      <label className="mb-3 block text-[12px] text-[var(--ink-2)]">
        Skill name
        <input
          value={name} onChange={(e) => setName(e.target.value)}
          placeholder="my-skill"
          className="mt-1 w-full rounded-lg px-3 py-2 font-mono text-[13px]"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
        />
      </label>
      <label className="mb-3 block text-[12px] text-[var(--ink-2)]">
        Host agent (builder session)
        <select
          value={agentId} onChange={(e) => setAgentId(e.target.value)}
          className="mt-1 w-full rounded-lg px-3 py-2 text-[13px]"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
        >
          <option value="">No builder session</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </label>
      {agentId && (
        <label className="mb-4 flex items-center gap-2 text-[12px] text-[var(--ink-2)]">
          <input type="checkbox" checked={launch} onChange={(e) => setLaunch(e.target.checked)} />
          Open a builder session (skill-creator loads automatically; draft files live in the agent's skill-drafts/)
        </label>
      )}
      {err && <p className="mb-3 text-[12px] text-[var(--danger)]">{err}</p>}
      <div className="flex justify-end gap-2">
        <button onClick={onClose} style={btn("secondary")}>Cancel</button>
        <button onClick={submit} disabled={!name.trim() || busy} style={btn("primary")}>
          {launch && agentId ? "Create & open session" : "Create draft"}
        </button>
      </div>
    </Dialog>
  );
}

function ImportUrlDialog({
  onClose, onSubmit,
}: {
  onClose: () => void;
  onSubmit: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title="Install from repository URL" onClose={onClose}>
      <p className="mb-3 text-[12px] text-[var(--ink-3)]">
        GitHub, GitLab, Bitbucket, or a direct .zip link — owner/repo shorthand
        works too. The repo is scanned for SKILL.md directories; you pick which
        to import as drafts. Nothing is published automatically.
      </p>
      <input
        value={url} onChange={(e) => setUrl(e.target.value)}
        placeholder="owner/repo or https://github.com/owner/repo[/tree/branch]"
        className="mb-4 w-full rounded-lg px-3 py-2 font-mono text-[13px]"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
      />
      <div className="flex justify-end gap-2">
        <button onClick={onClose} style={btn("secondary")}>Cancel</button>
        <button
          onClick={() => { setBusy(true); onSubmit(url.trim()); }}
          disabled={!url.trim() || busy}
          style={btn("primary")}
        >
          {busy ? "Fetching…" : "Fetch"}
        </button>
      </div>
    </Dialog>
  );
}

function PublishDialog({
  skill, agents, onClose, onPublished,
}: {
  skill: SkillDetail;
  agents: Agent[];
  onClose: () => void;
  onPublished: () => void;
}) {
  const isPromote = skill.status === "published" && skill.scope === "agent-local";
  const [scope, setScope] = useState<"global" | "agent-local">(isPromote ? "global" : "global");
  const [ownerId, setOwnerId] = useState(skill.owner_agent_id ?? agents[0]?.id ?? "");
  const [availability, setAvailability] = useState<"all" | "selected">("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = {
        availability,
        agent_ids: availability === "selected" ? selectedIds : undefined,
        change_summary: summary || undefined,
      };
      if (isPromote) {
        await api.promoteSkill(skill.id, body);
      } else {
        await api.publishSkill(skill.id, {
          ...body,
          scope,
          owner_agent_id: scope === "agent-local" ? ownerId || undefined : undefined,
        });
      }
      onPublished();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "publish failed");
      setBusy(false);
    }
  };

  return (
    <Dialog title={isPromote ? `Promote "${skill.name}" to global` : `Publish "${skill.name}"`} onClose={onClose}>
      {!isPromote && (
        <div className="mb-3">
          <p className="mb-1 text-[12px] text-[var(--ink-2)]">Scope</p>
          <div className="flex gap-2">
            {(["global", "agent-local"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className="rounded-lg px-3 py-2 text-[12px]"
                style={{
                  background: scope === s ? "var(--ink)" : "var(--surface)",
                  color: scope === s ? "var(--white)" : "var(--ink)",
                  border: "1px solid var(--border)", cursor: "pointer",
                }}
              >
                {s === "global" ? "Global (all/selected agents)" : "Agent-local"}
              </button>
            ))}
          </div>
        </div>
      )}
      {!isPromote && scope === "agent-local" && (
        <label className="mb-3 block text-[12px] text-[var(--ink-2)]">
          Owner agent
          <select
            value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
            className="mt-1 w-full rounded-lg px-3 py-2 text-[13px]"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
          >
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
      )}
      {(isPromote || scope === "global") && (
        <div className="mb-3">
          <p className="mb-1 text-[12px] text-[var(--ink-2)]">Availability</p>
          <div className="flex gap-2">
            {(["all", "selected"] as const).map((a) => (
              <button
                key={a}
                onClick={() => setAvailability(a)}
                className="rounded-lg px-3 py-1.5 text-[12px]"
                style={{
                  background: availability === a ? "var(--ink)" : "var(--surface)",
                  color: availability === a ? "var(--white)" : "var(--ink)",
                  border: "1px solid var(--border)", cursor: "pointer",
                }}
              >
                {a === "all" ? "All agents" : "Selected agents"}
              </button>
            ))}
          </div>
          {availability === "selected" && (
            <div className="mt-2 max-h-32 overflow-y-auto rounded-lg p-2" style={{ border: "1px solid var(--border)" }}>
              {agents.map((a) => (
                <label key={a.id} className="flex items-center gap-2 py-1 text-[12px] text-[var(--ink-2)]">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(a.id)}
                    onChange={(e) =>
                      setSelectedIds(
                        e.target.checked ? [...selectedIds, a.id] : selectedIds.filter((x) => x !== a.id),
                      )
                    }
                  />
                  {a.name}
                </label>
              ))}
            </div>
          )}
        </div>
      )}
      <input
        value={summary} onChange={(e) => setSummary(e.target.value)}
        placeholder="Change summary (optional)"
        className="mb-4 w-full rounded-lg px-3 py-2 text-[13px]"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
      />
      {err && <p className="mb-3 text-[12px] text-[var(--danger)]">{err}</p>}
      <div className="flex justify-end gap-2">
        <button onClick={onClose} style={btn("secondary")}>Cancel</button>
        <button onClick={submit} disabled={busy} style={btn("primary")}>
          {isPromote ? "Promote" : "Publish"}
        </button>
      </div>
    </Dialog>
  );
}

function CandidatePicker({
  candidates, onCancel, onImport,
}: {
  candidates: SkillCandidate[];
  onCancel: () => void;
  onImport: (paths: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(candidates.map((c) => c.path));
  return (
    <Dialog title="Multiple skills found" onClose={onCancel}>
      <p className="mb-3 text-[12px] text-[var(--ink-3)]">
        This archive contains {candidates.length} skills. Select which to import as drafts:
      </p>
      <div className="mb-4 max-h-64 overflow-y-auto rounded-lg" style={{ border: "1px solid var(--border)" }}>
        {candidates.map((c) => (
          <label key={c.path} className="flex items-start gap-2 border-b border-[var(--border)]/50 px-3 py-2 text-[12px]">
            <input
              type="checkbox" className="mt-0.5"
              checked={selected.includes(c.path)}
              onChange={(e) =>
                setSelected(e.target.checked ? [...selected, c.path] : selected.filter((x) => x !== c.path))
              }
            />
            <span className="min-w-0">
              <span className="block font-medium text-[var(--ink)]">{c.name || c.dir_name}</span>
              <span className="block truncate text-[var(--ink-3)]">{c.description || c.path || "(archive root)"}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} style={btn("secondary")}>Cancel</button>
        <button onClick={() => onImport(selected)} disabled={!selected.length} style={btn("primary")}>
          Import {selected.length} draft{selected.length !== 1 ? "s" : ""}
        </button>
      </div>
    </Dialog>
  );
}

function Dialog({
  title, children, onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.4)" }}
      onClick={onClose}
    >
      <div
        className="w-[440px] rounded-xl p-5"
        style={{ background: "var(--white)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-[var(--ink)]">{title}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-3)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
