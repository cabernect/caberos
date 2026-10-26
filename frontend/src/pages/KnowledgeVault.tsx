import { useCallback, useEffect, useRef, useState } from "react";
import {
  FileText,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { StatusWord } from "@/components/ui/status-word";
import { WarningBanner } from "@/components/ui/warning-banner";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/lib/confirmHook";
import { api } from "@/lib/api";
import type {
  KnowledgeDocument,
  KnowledgeResult,
  KnowledgeScope,
} from "@/lib/types";
import { formatBytes } from "@/lib/knowledge";
import { useDesktopFileDrop } from "@/lib/desktopFileDrop";

const EMPTY_STRUCTURE = {
  sections: [],
  pages: [],
  tables: [],
  images: [],
  sheets: [],
};

export function KnowledgeVault() {
  const { scope } = useParams<{ scope?: string }>();
  return scope ? <KnowledgeScopeDetail scope={scope} /> : <KnowledgeOverview />;
}

function useVaultNavigation() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();
  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };
  const handleNavigate = (page: NavKey) => {
    navigate(NAV_ROUTES[page]);
  };
  return {
    sidebarCollapsed,
    setSidebarCollapsed,
    navigate,
    handleLogout,
    handleNavigate,
  };
}

function Shell({
  children,
  ...navigation
}: { children: React.ReactNode } & ReturnType<typeof useVaultNavigation>) {
  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      <DashboardSidebar
        active="vault"
        onLogout={navigation.handleLogout}
        collapsed={navigation.sidebarCollapsed}
        onToggleCollapse={() =>
          navigation.setSidebarCollapsed(!navigation.sidebarCollapsed)
        }
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-auto">
        {children}
      </div>
    </div>
  );
}

function KnowledgeOverview() {
  const navigation = useVaultNavigation();
  const [scopes, setScopes] = useState<KnowledgeScope[]>([]);
  const [sharedDocs, setSharedDocs] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [askText, setAskText] = useState("");
  const [askResults, setAskResults] = useState<KnowledgeResult[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listKnowledgeOverview()
      .then((overview) => setScopes(overview.scopes))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoading(false));
    api
      .listKnowledgeScope("shared")
      .then((r) => setSharedDocs(r.documents))
      .catch(() => {});
  }, []);

  useEffect(load, [load]);

  const shared = scopes.find((s) => s.id === "shared");
  const agentScopes = scopes.filter((s) => s.id !== "shared");
  const emptyAgents = agentScopes.filter((s) => s.document_count === 0).length;

  const ask = async () => {
    const q = askText.trim();
    if (!q || asking) return;
    setAsking(true);
    try {
      setAskResults((await api.searchKnowledge(q, 8)).results);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setAsking(false);
    }
  };

  const uploadShared = async (files: FileList | File[]) => {
    setUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        await api.uploadKnowledgeScope("shared", file);
      }
      const r = await api.listKnowledgeScope("shared");
      setSharedDocs(r.documents);
      load();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Shell {...navigation}>
      <PageHeader
        breadcrumbs={[{ label: "Capabilities" }, { label: "Knowledge Vault" }]}
        title="Knowledge Vault"
        subtitle={`${scopes.length} scope${scopes.length === 1 ? "" : "s"} · what your agents can read and remember.`}
      />
      <main className="px-8 pb-10">
        <div className="pt-4">
          <PageIntro def={INTRO_BY_KEY.vault} />
        </div>
        {error && (
          <WarningBanner tone="danger" className="mb-4">{error}</WarningBanner>
        )}
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
            <input
              value={askText}
              onChange={(e) => setAskText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void ask()}
              placeholder="Ask the vault anything"
              className="h-[34px] w-[260px] rounded-md border border-line bg-surface pl-8 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-faint"
            />
          </div>
        </div>

        {askResults !== null && (
          <SectionCard
            title={`Vault answers for "${askText.trim()}"`}
            className="mt-4"
            action={
              <button
                type="button"
                onClick={() => { setAskResults(null); setAskText(""); }}
                className="cursor-pointer text-[13px] text-ink-muted hover:text-ink"
              >
                Clear
              </button>
            }
          >
            {askResults.length === 0 ? (
              <p className="text-[13px] text-ink-faint">No passages matched.</p>
            ) : (
              <div className="space-y-2">
                {askResults.map((r) => {
                  const scopeName = r.agent_id == null
                    ? "Shared"
                    : scopes.find((s) => s.id === r.agent_id)?.name ?? r.agent_id;
                  return (
                    <article key={r.chunk_id} className="rounded-md border border-line bg-sunken/40 p-3">
                      <p className="text-[13px] leading-5 text-ink">{r.text}</p>
                      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-faint">
                        <span className="rounded-full bg-accent-tint px-1.5 py-0.5 font-medium text-accent">
                          {scopeName}
                        </span>
                        <span className="truncate">
                          {r.source_path}
                          {r.page_number ? ` · page ${r.page_number}` : ""}
                          {r.sheet_name ? ` · ${r.sheet_name}` : ""}
                        </span>
                      </p>
                    </article>
                  );
                })}
              </div>
            )}
          </SectionCard>
        )}

        {loading ? (
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            {[0, 1].map((i) => (
              <div key={i} className="h-[320px] animate-pulse rounded-lg border border-line bg-surface" />
            ))}
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
              <SectionCard
                title="Shared knowledge"
                action={
                  <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
                    <Upload className="h-3.5 w-3.5" />
                    {uploading ? "Indexing…" : "Upload"}
                  </Button>
                }
              >
                <p className="-mt-1 mb-3 text-[13px] text-ink-muted">
                  Inherited by every agent · {shared?.document_count ?? 0} document
                  {shared?.document_count === 1 ? "" : "s"} ·{" "}
                  {(shared?.chunk_count ?? 0).toLocaleString()} chunks
                </p>
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  onDragEnter={(e) => { e.preventDefault(); if (!uploading) setDragActive(true); }}
                  onDragOver={(e) => e.preventDefault()}
                  onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragActive(false);
                    if (!uploading && e.dataTransfer.files.length) void uploadShared(e.dataTransfer.files);
                  }}
                  disabled={uploading}
                  className={`flex w-full cursor-pointer flex-col items-center rounded-md border border-dashed px-5 py-7 text-[13px] transition-colors disabled:opacity-50 ${
                    dragActive ? "border-accent bg-accent-tint/40" : "border-line hover:bg-sunken/50"
                  }`}
                >
                  <Upload className="h-5 w-5 text-accent" />
                  <span className="mt-2 text-ink-muted">
                    <span className="font-medium text-ink">Drop files here</span> to index them
                  </span>
                  <span className="mt-0.5 text-[11px] text-ink-faint">MD, TXT, PDF, DOCX</span>
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  accept=".md,.markdown,.txt,.pdf,.docx"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files) void uploadShared(e.target.files);
                    e.target.value = "";
                  }}
                />
                {sharedDocs.length > 0 && (
                  <div className="mt-3 divide-y divide-line border-t border-line">
                    {sharedDocs.slice(0, 8).map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => navigation.navigate("/vault/shared")}
                        className="flex w-full cursor-pointer items-center gap-3 py-2.5 text-left transition-colors hover:bg-sunken/50"
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sunken">
                          <FileText className="h-4 w-4 text-ink-muted" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-ink">{d.display_name}</span>
                          <span className="block truncate text-[11px] text-ink-faint">
                            {d.display_name.split(".").pop()?.toUpperCase() ?? "file"} ·{" "}
                            {(d.chunk_count ?? 0).toLocaleString()} chunks
                          </span>
                        </span>
                        <StatusWord
                          status={d.status === "indexed" ? "success" : d.status === "failed" ? "failed" : "idle"}
                          label={d.status.charAt(0).toUpperCase() + d.status.slice(1)}
                        />
                      </button>
                    ))}
                    {sharedDocs.length > 8 && (
                      <button
                        type="button"
                        onClick={() => navigation.navigate("/vault/shared")}
                        className="block w-full cursor-pointer py-2 text-[12px] text-ink-muted hover:text-ink"
                      >
                        + {sharedDocs.length - 8} more — open scope
                      </button>
                    )}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Agent scopes" bodyClassName="px-0 py-0">
                <p className="border-b border-line px-4 pb-3 text-[13px] text-ink-muted">
                  Private to one agent.
                  {emptyAgents === agentScopes.length && agentScopes.length > 0
                    ? ` All ${agentScopes.length} are empty — shared knowledge covers them for now.`
                    : ""}
                </p>
                {agentScopes.length === 0 ? (
                  <p className="px-4 py-8 text-center text-[13px] text-ink-faint">
                    No agents yet — their private scopes appear here.
                  </p>
                ) : (
                  <div className="divide-y divide-line">
                    {agentScopes.map((s) => (
                      <AgentScopeRow
                        key={s.id}
                        scope={s}
                        onOpen={() => navigation.navigate(`/vault/${s.id}`)}
                      />
                    ))}
                  </div>
                )}
              </SectionCard>
          </div>
        )}
      </main>
    </Shell>
  );
}

export function AgentScopeRow({
  scope,
  onOpen,
}: {
  scope: KnowledgeScope;
  onOpen: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-tint text-[13px] font-semibold text-accent">
        {scope.name.slice(0, 1).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
        {scope.name}
      </span>
      <StatusWord
        status={scope.document_count > 0 ? "success" : "idle"}
        label={
          scope.document_count > 0
            ? `${scope.document_count} doc${scope.document_count === 1 ? "" : "s"} · ${scope.chunk_count.toLocaleString()} chunks`
            : "Empty"
        }
      />
      <button
        type="button"
        onClick={onOpen}
        className="cursor-pointer text-[13px] font-medium text-accent hover:underline"
      >
        {scope.document_count > 0 ? "Open" : "Add"}
      </button>
    </div>
  );
}

function KnowledgeScopeDetail({ scope }: { scope: string }) {
  const navigation = useVaultNavigation();
  const { confirm } = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [results, setResults] = useState<KnowledgeResult[]>([]);
  const [query, setQuery] = useState("");
  const [working, setWorking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const isShared = scope === "shared";
  const scopeName = isShared ? "Shared Knowledge" : scope;

  useEffect(() => {
    api
      .listKnowledgeScope(scope)
      .then((response) => setDocuments(response.documents))
      .catch((reason) => setError(String(reason)));
  }, [scope]);

  const uploadFiles = async (files: FileList | File[]) => {
    setWorking(true);
    setUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        const document = await api.uploadKnowledgeScope(scope, file);
        setDocuments((current) =>
          [...current.filter((item) => item.id !== document.id), document].sort(
            (a, b) => a.display_name.localeCompare(b.display_name),
          ),
        );
      }
    } catch (reason) {
      setError(String(reason));
    } finally {
      setWorking(false);
      setUploading(false);
    }
  };

  useDesktopFileDrop({
    onFiles: (files) => {
      if (!working) void uploadFiles(files);
    },
    onDraggingChange: setDragActive,
    onError: () => setError("The dropped file could not be read."),
  });

  const search = async () => {
    if (!query.trim()) return;
    setWorking(true);
    setError("");
    try {
      setResults((await api.searchKnowledgeScope(scope, query.trim())).results);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setWorking(false);
    }
  };

  const reindex = async (document: KnowledgeDocument) => {
    setReindexing(document.id);
    setError("");
    try {
      const updated = await api.reindexKnowledgeDocument(scope, document.id);
      setDocuments((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setError(String(reason));
    } finally {
      setReindexing(null);
    }
  };

  const remove = async (document: KnowledgeDocument) => {
    const confirmed = await confirm({
      title: "Delete document",
      message: `Delete ${document.display_name}? This will remove it and its indexed chunks.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.deleteKnowledgeScope(scope, document.id);
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      );
    } catch (reason) {
      setError(String(reason));
    }
  };

  return (
    <Shell {...navigation}>
      <PageHeader
        breadcrumbs={[
          { label: "Capabilities" },
          { label: "Knowledge Vault", onClick: () => navigation.navigate("/vault") },
          { label: scopeName },
        ]}
        title={scopeName}
        subtitle={isShared ? "Available to every agent" : "Private agent knowledge"}
      />
      <main className="mx-auto w-full max-w-5xl space-y-5 px-8 py-7">
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <section
          className="rounded-xl p-5"
          style={{
            border: "1px solid var(--line)",
            background: "var(--surface)",
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-[var(--ink)]">
              Upload documents
            </h2>
            {uploading && (
              <p role="status" className="text-xs text-[var(--accent)]">
                Uploading and indexing…
              </p>
            )}
          </div>
          <p className="mt-1 text-xs text-[var(--ink-faint)]">
            MD, TXT, PDF, DOCX · up to 250 MB per file
          </p>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault();
              if (!working) setDragActive(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              event.preventDefault();
              setDragActive(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              if (!working && event.dataTransfer.files.length > 0) {
                void uploadFiles(event.dataTransfer.files);
              }
            }}
            disabled={working}
            className="mt-4 flex w-full cursor-pointer flex-col items-center rounded-md border border-dashed px-5 py-7 text-sm text-[var(--ink-muted)] transition-colors hover:bg-[var(--surface)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              borderColor: dragActive ? "var(--accent)" : "var(--line)",
              background: dragActive ? "var(--accent-tint)" : undefined,
            }}
          >
            <Upload className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <span className="mt-2">Choose files or drag them here</span>
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".md,.markdown,.txt,.pdf,.docx"
            className="hidden"
            onChange={(event) => {
              if (event.target.files) void uploadFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </section>
        <section
          className="overflow-hidden rounded-xl"
          style={{
            border: "1px solid var(--line)",
            background: "var(--surface)",
          }}
        >
          <div
            className="border-b px-5 py-4"
            style={{ borderColor: "var(--line)" }}
          >
            <h2 className="text-sm font-semibold text-[var(--ink)]">
              Indexed documents
            </h2>
          </div>
          {documents.length === 0 ? (
            <p className="px-5 py-8 text-sm text-[var(--ink-faint)]">
              No documents indexed.
            </p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead
                className="border-b text-[11px] uppercase tracking-wide text-[var(--ink-faint)]"
                style={{ borderColor: "var(--line)" }}
              >
                <tr>
                  <th className="px-5 py-3 font-medium">Document</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {documents.map((document) => {
                  const structure = {
                    sections:
                      document.structure?.sections ?? EMPTY_STRUCTURE.sections,
                    pages: document.structure?.pages ?? EMPTY_STRUCTURE.pages,
                    tables:
                      document.structure?.tables ?? EMPTY_STRUCTURE.tables,
                    images:
                      document.structure?.images ?? EMPTY_STRUCTURE.images,
                    sheets:
                      document.structure?.sheets ?? EMPTY_STRUCTURE.sheets,
                  };
                  return (
                    <tr key={document.id}>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <FileText
                            className="h-4 w-4"
                            style={{ color: "var(--accent)" }}
                          />
                          <div>
                            <p className="text-[var(--ink)]">
                              {document.display_name}
                            </p>
                            <p className="text-xs text-[var(--ink-faint)]">
                              {document.source_path} ·{" "}
                              {formatBytes(document.size_bytes)}
                            </p>
                            <p className="text-xs text-[var(--ink-faint)]">
                              {document.chunk_count ?? 0} chunks ·{" "}
                              {structure.sections.length} sections ·{" "}
                              {structure.pages.length} pages ·{" "}
                              {structure.tables.length} tables ·{" "}
                              {structure.images.length} images
                            </p>
                            {document.error && (
                              <p className="mt-1 text-xs text-[var(--danger)]">
                                {document.error}
                              </p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-xs text-[var(--accent)]">
                        {document.status}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex justify-end gap-3">
                          <button
                            type="button"
                            onClick={() => void reindex(document)}
                            disabled={working || reindexing === document.id}
                            className="cursor-pointer text-xs text-[var(--ink-muted)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {reindexing === document.id
                              ? "Indexing…"
                              : "Re-index"}
                          </button>
                          <button
                            type="button"
                            onClick={() => void remove(document)}
                            aria-label={`Delete ${document.display_name}`}
                            className="cursor-pointer text-[var(--ink-faint)] hover:text-[var(--danger)]"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
        <section
          className="rounded-xl"
          style={{
            border: "1px solid var(--line)",
            background: "var(--surface)",
          }}
        >
          <div
            className="border-b px-5 py-4"
            style={{ borderColor: "var(--line)" }}
          >
            <h2 className="text-sm font-semibold text-[var(--ink)]">
              Retrieval preview
            </h2>
            <div className="mt-3 flex gap-3">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && void search()}
                placeholder="Search this scope…"
                className="min-w-0 flex-1 rounded-md border bg-transparent px-3 py-2 text-sm outline-none"
                style={{ borderColor: "var(--line)", color: "var(--ink)" }}
              />
              <button
                type="button"
                onClick={() => void search()}
                disabled={working || !query.trim()}
                className="flex cursor-pointer items-center gap-2 rounded-md border px-4 py-2 text-sm disabled:opacity-50"
                style={{ borderColor: "var(--line)", color: "var(--ink-muted)" }}
              >
                <Search className="h-4 w-4" /> Search
              </button>
            </div>
          </div>
          <div className="space-y-3 p-5">
            {results.length === 0 ? (
              <p className="text-sm text-[var(--ink-faint)]">
                Search results will appear here.
              </p>
            ) : (
              results.map((result) => (
                <article
                  key={result.chunk_id}
                  className="rounded-md border p-3"
                  style={{ borderColor: "var(--line)" }}
                >
                  <p className="text-sm leading-6 text-[var(--ink)]">
                    {result.text}
                  </p>
                  <p className="mt-2 text-xs text-[var(--ink-faint)]">
                    {result.source_path}
                    {result.page_number ? ` · page ${result.page_number}` : ""}
                    {result.sheet_name ? ` · ${result.sheet_name}` : ""}
                  </p>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </Shell>
  );
}
