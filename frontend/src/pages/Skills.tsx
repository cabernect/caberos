import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, ChevronRight, ChevronDown, File, Folder, FolderOpen,
  Sparkles, Upload, Trash2, FileText,
  Search, Package, Plus, Globe, Download, History, Archive,
  Ban, RotateCcw, Link2, X,
} from "lucide-react";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { IconTile } from "@/components/ui/icon-tile";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { api, skillBackend } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { useResizableWidth } from "@/lib/useResizableWidth";
import type {
  Agent, SkillCandidate, SkillDetail, SkillInfo,
} from "@/lib/types";
import { PreviewPanel } from "@/components/previews/PreviewPanel";
import { formatBytes } from "@/components/previews/renderers";
import { Markdown } from "@/components/Markdown";
import { Select } from "@/components/ui/select";

type ViewKey = "all" | "built-in" | "global" | "agent-local" | "drafts" | "archived";
type DetailTab = "overview" | "instructions" | "resources" | "history" | "usage";

const VIEWS: { key: ViewKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "built-in", label: "Built-in" },
  { key: "global", label: "Global" },
  { key: "agent-local", label: "Agent" },
  { key: "drafts", label: "Drafts" },
  { key: "archived", label: "Archived" },
];

const STATUS_STYLE: Record<string, string> = {
  published: "var(--success)",
  draft: "var(--warning)",
  disabled: "var(--ink-2)",
  archived: "var(--ink-3)",
};

const MAIN_MIN_WIDTH = 520;

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
  const [viewCounts, setViewCounts] = useState<Partial<Record<ViewKey, number>>>({});

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
  } = useResizableWidth({ initial: 460, min: 380, max: 1100, storageKey: "caberos.skillDrawer.width" });

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
  const [addMenuOpen, setAddMenuOpen] = useState(false);
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

  const loadSkills = useCallback(async (silent = false) => {
    const seq = ++loadSeq.current;
    try {
      if (!silent) setLoading(true);
      const data = await api.listSkills(
        view,
        view === "agent-local" && agentFilter ? agentFilter : undefined,
        search || undefined,
      );
      if (seq !== loadSeq.current) return;
      setSkills(data.skills);
      setError(null);
      // Refresh tab counts alongside the visible list (search narrows the
      // list but counts stay global).
      Promise.all(
        VIEWS.map(async (v) => {
          const r = await api.listSkills(v.key);
          return [v.key, r.count] as const;
        }),
      )
        .then((entries) => {
          if (seq !== loadSeq.current) return;
          setViewCounts(Object.fromEntries(entries));
        })
        .catch(() => {});
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setError(e instanceof Error ? e.message : "Failed to load skills");
    } finally {
      if (!silent && seq === loadSeq.current) setLoading(false);
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
    if (selectedId) {
      try {
        setDetail(await api.skillDetail(selectedId));
      } catch {
        /* detail gone */
      }
    }
    await loadSkills(true);
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
    navigate(NAV_ROUTES[page]);
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
      await loadSkills(true);
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
      await loadSkills(true);
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

  const scopeChip = (s: SkillInfo) => {
    const label =
      s.scope === "agent-local" && s.owner_name
        ? `Agent · ${s.owner_name}`
        : s.scope === "built-in"
          ? "Built-in"
          : "Global";
    return (
      <span
        className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
          s.scope === "agent-local" ? "bg-accent-tint text-accent" : "bg-sunken text-ink-muted"
        }`}
      >
        {label}
      </span>
    );
  };

  const usedByLabel = (s: SkillInfo) => {
    if (s.assigned_names.length) return `Used by ${s.assigned_names.join(", ")}`;
    if ((s.activation_count ?? 0) > 0)
      return `Used ${s.activation_count} time${s.activation_count !== 1 ? "s" : ""}`;
    return "No recorded use";
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
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--ground)" }}>
      <DashboardSidebar
        active="skills"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div ref={contentRef} className="relative flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Capabilities" }, { label: "Skills" }]}
          title="Skills"
          subtitle={`${viewCounts.all ?? skills.length} skills · versioned, scoped library — control what each agent knows how to do.`}
          actions={
            <div className="relative">
              <input ref={fileInputRef} type="file" accept=".zip" onChange={handleZipImport} className="hidden" />
              <Button onClick={() => setAddMenuOpen(!addMenuOpen)}>
                <Plus />Add skill<ChevronDown className="h-3.5 w-3.5 opacity-70" />
              </Button>
              {addMenuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setAddMenuOpen(false)} />
                  <div className="absolute right-0 top-full z-20 mt-1.5 min-w-[170px] overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-lg">
                    {(
                      [
                        { icon: Sparkles, label: "Create skill", act: () => setShowCreate(true) },
                        { icon: Upload, label: "Import .zip", act: () => fileInputRef.current?.click() },
                        { icon: Link2, label: "From URL", act: () => setShowImportUrl(true) },
                      ] as const
                    ).map(({ icon: Ic, label, act }) => (
                      <button
                        key={label}
                        onClick={() => {
                          setAddMenuOpen(false);
                          act();
                        }}
                        className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-[12.5px] text-ink-2 transition-colors hover:bg-sunken hover:text-ink"
                      >
                        <Ic className="h-3.5 w-3.5" /> {label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          }
        />

        <div className="px-6 pt-4">
          <PageIntro def={INTRO_BY_KEY.skills} />
        </div>

        {/* Notices + filter row — pinned below the header */}
        <div className="px-6 pb-4">
          {notice && (
            <div className="mb-3 flex items-center justify-between rounded-lg bg-accent-tint px-4 py-2.5 text-[13px] text-accent">
              {notice}
              <button onClick={() => setNotice(null)} className="text-ink-faint hover:text-ink"><X className="h-3.5 w-3.5" /></button>
            </div>
          )}
          {error && (
            <div className="mb-3 flex items-center justify-between rounded-lg bg-danger-tint px-4 py-2.5 text-[13px] text-danger">
              {error}
              <button onClick={() => setError(null)} className="text-ink-faint hover:text-ink"><X className="h-3.5 w-3.5" /></button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <FilterPills
              pills={VIEWS.map((v) => ({ key: v.key, label: v.label, count: viewCounts[v.key] }))}
              active={view}
              onChange={(k) => setView(k as ViewKey)}
              variant="segmented"
            />
            <div className="ml-auto flex items-center gap-2">
              {view === "agent-local" && (
                <Select
                  value={agentFilter}
                  onChange={setAgentFilter}
                  options={[
                    { value: "", label: "All agents" },
                    ...agents.map((a) => ({ value: a.id, label: a.name })),
                  ]}
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink"
                  panelClassName="text-[13px]"
                />
              )}
              <div className="relative w-[240px]">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                <input
                  type="text" value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search skills"
                  className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {loading ? (
            <p className="py-20 text-center text-[14px] text-ink-faint">Loading skills…</p>
          ) : skills.length === 0 ? (
            <EmptyState
              icon={Package}
              title={view === "drafts" ? "No drafts" : "No skills in this view"}
              action={<Button onClick={() => setShowCreate(true)}><Plus />Create skill</Button>}
            >
              {view === "drafts"
                ? "Drafts appear here when a builder session or an import creates one."
                : "Create a skill or import one to grow the library."}
            </EmptyState>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {skills.map((skill) => {
                const enabled = skill.status === "published";
                const toggleable = skill.status === "published" || skill.status === "disabled";
                return (
                <div
                  key={skill.id}
                  className="group cursor-pointer rounded-xl border border-line bg-surface p-4 transition hover:border-ink-faint/50"
                  onClick={() => openDetail(skill.id)}
                >
                  <div className="flex items-start gap-3">
                    <IconTile icon={Sparkles} tone="accent" size="md" />
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate font-mono text-[13px] font-semibold text-ink">{skill.name}</h3>
                      {skill.builder_session_id && (
                        <span className="text-[11px] text-accent" title="Builder session active">building…</span>
                      )}
                    </div>
                    {(skill.status === "draft" ||
                      (skill.scope !== "built-in" && skill.status !== "published")) && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(skill); }}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-ink-faint opacity-0 transition group-hover:opacity-100 hover:bg-danger-tint hover:text-danger"
                        title={skill.status === "draft" ? "Delete draft" : "Purge skill"}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {toggleable ? (
                      <Toggle
                        checked={enabled}
                        onCheckedChange={(v) => handleStatus(skill, v ? "published" : "disabled")}
                        aria-label={enabled ? `Disable ${skill.name}` : `Enable ${skill.name}`}
                      />
                    ) : (
                      statusBadge(skill)
                    )}
                  </div>

                  <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-ink-muted">
                    {skill.description || "No description"}
                  </p>

                  <div className="mt-3 flex items-center gap-2 border-t border-line pt-3 text-[12px] text-ink-faint">
                    {scopeChip(skill)}
                    {skill.current_revision != null && (
                      <span className="font-mono text-[11px]">rev {skill.current_revision}</span>
                    )}
                    <span className="flex items-center gap-1 font-mono text-[11px]">
                      <FileText className="h-3 w-3" />
                      {skill.resource_count}
                    </span>
                    <span className="ml-auto truncate" title={
                      (skill.assigned_names.length
                        ? `Available to: ${skill.assigned_names.join(", ")}`
                        : "Recorded activations only — earlier use may be unrecorded") +
                      (skill.last_used_at
                        ? ` · Last used ${new Date(skill.last_used_at).toLocaleDateString()}`
                        : "")
                    }>
                      {usedByLabel(skill)}
                    </span>
                  </div>
                </div>
                );
              })}
            </div>
          )}

          {/* Draft-with-agent banner */}
          <div className="mt-4 flex items-center gap-3 rounded-xl border border-dashed border-line bg-surface px-4 py-3.5">
            <IconTile icon={Sparkles} tone="accent" size="sm" />
            <p className="min-w-0 flex-1 text-[13px] text-ink-muted">
              <span className="font-medium text-ink">Describe a skill, let an agent draft it.</span>{" "}
              Uses skill-creator and saves it as a draft you can review.
            </p>
            <Button variant="secondary" onClick={() => setShowCreate(true)}>
              <Sparkles />Draft with an agent
            </Button>
          </div>
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
              <p className="truncate font-mono text-[14px] font-semibold text-[var(--ink)]">{detail.name}</p>
              <p className="text-[11px] capitalize text-[var(--ink-3)]">
                {detail.scope}
                {detail.owner_name ? ` · ${detail.owner_name}` : ""}
                {detail.current_revision != null ? ` · Revision ${detail.current_revision}` : ""}
                {` · ${detail.status}`}
                {detail.validation.errors.length === 0 && detail.validation.warnings.length === 0 && (
                  <span className="text-[var(--success)]"> · ● Valid</span>
                )}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {(detail.status === "published" || detail.status === "disabled") && (
                <span className="text-[11px] text-[var(--ink-3)]">{detail.status === "published" ? "Enabled" : "Disabled"}</span>
              )}
              {(detail.status === "published" || detail.status === "disabled") && (
                <Toggle
                  checked={detail.status === "published"}
                  onCheckedChange={(v) => handleStatus(detail, v ? "published" : "disabled")}
                  size="sm"
                  aria-label={detail.status === "published" ? "Disable skill" : "Enable skill"}
                  title={detail.status === "published" ? "Disable skill" : "Enable skill"}
                />
              )}
              <button onClick={closeDetail} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-3)" }}>
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Tab bar — same segmented pill track as the rest of the app */}
          <div className="border-b border-line px-4 py-2.5">
            <FilterPills
              pills={(["overview", "instructions", "resources", "history", "usage"] as DetailTab[]).map((t) => ({
                key: t,
                label: t[0].toUpperCase() + t.slice(1),
              }))}
              active={detailTab}
              onChange={(k) => setDetailTab(k as DetailTab)}
              variant="segmented"
            />
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
                    <Select
                      value={String(filesRevision ?? detail.current_revision ?? "")}
                      onChange={(v) => loadFiles(v ? Number(v) : undefined)}
                      options={[
                        {
                          value: "",
                          label: detail.scope === "agent-local" ? "live copy" : "current",
                        },
                        ...detail.revisions.map((r) => ({
                          value: String(r.revision_number),
                          label: `rev ${r.revision_number}`,
                        })),
                      ]}
                      className="rounded border border-line bg-surface px-2 py-1 text-[12px] text-ink"
                      align="left" panelClassName="text-[12px]"
                    />
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
  const toolNames = detail.allowed_tools.split(/[,\s]+/).filter(Boolean);
  const toolGroups: [string, string[]][] = [];
  for (const name of toolNames) {
    const group = name.startsWith("browser_") ? "Browser" : name.startsWith("web_") ? "Web" : "Other";
    const existing = toolGroups.find(([g]) => g === group);
    if (existing) existing[1].push(name);
    else toolGroups.push([group, [name]]);
  }
  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">What it's for</p>
        <p className="text-[13px] leading-relaxed text-[var(--ink)]">{detail.description || "—"}</p>
      </div>

      {detail.assigned_names.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">Used by</p>
          <div className="flex flex-wrap gap-1.5">
            {detail.assigned_names.map((n) => (
              <span
                key={n}
                className="rounded-full bg-ground px-2.5 py-1 text-[12px] font-medium text-ink-2"
              >
                {n}
              </span>
            ))}
          </div>
        </div>
      )}

      {toolGroups.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">
            Tools it can use · {toolNames.length}
          </p>
          <div className="flex flex-col gap-1.5">
            {toolGroups.map(([group, names]) => (
              <div key={group} className="flex items-baseline gap-2">
                <span className="w-14 shrink-0 text-[12px] text-[var(--ink-3)]">{group}</span>
                <div className="flex flex-wrap gap-1.5">
                  {names.map((n) => (
                    <span
                      key={n}
                      className="rounded-md bg-ground px-2 py-0.5 font-mono text-[11px] text-ink-2"
                    >
                      {n}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.compatibility && (
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">Requirements</p>
          <p className="text-[12px] text-[var(--ink-2)]">{detail.compatibility}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 text-[12px]">
        <Field label="Scope" value={detail.scope + (detail.owner_name ? ` (${detail.owner_name})` : "")} />
        <Field label="Status" value={detail.status} />
        <Field label="Revision" value={detail.current_revision != null ? `#${detail.current_revision}` : "—"} />
        <Field label="Availability" value={detail.scope === "global" ? detail.availability : "—"} />
        {detail.license && <Field label="License" value={detail.license} />}
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
        <Select
          value={agentId} onChange={setAgentId}
          options={[
            { value: "", label: "No builder session" },
            ...agents.map((a) => ({ value: a.id, label: a.name })),
          ]}
          className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink"
          align="left" panelClassName="text-[13px]"
        />
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
          <Select
            value={ownerId} onChange={setOwnerId}
            options={agents.map((a) => ({ value: a.id, label: a.name }))}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink"
            align="left" panelClassName="text-[13px]"
          />
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
