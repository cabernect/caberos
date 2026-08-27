import { useEffect, useRef, useState } from "react";
import { ArrowRight, Database, FileText, Search, Trash2, Upload } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/PageHeader";
import { useConfirm } from "@/lib/confirm";
import { api } from "@/lib/api";
import type { KnowledgeDocument, KnowledgeResult, KnowledgeScope } from "@/lib/types";
import { formatBytes } from "@/lib/knowledge";
import { useDesktopFileDrop } from "@/lib/desktopFileDrop";

const EMPTY_STRUCTURE = { sections: [], pages: [], tables: [], images: [], sheets: [] };

export function KnowledgeVault() {
  const { scope } = useParams<{ scope?: string }>();
  return scope ? <KnowledgeScopeDetail scope={scope} /> : <KnowledgeOverview />;
}

function useVaultNavigation() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();
  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    window.location.assign("/login");
  };
  const handleNavigate = (page: NavKey) => {
    const routes: Partial<Record<NavKey, string>> = {
      agents: "/agents", settings: "/settings", skills: "/skills", scheduler: "/scheduler",
      mcps: "/mcps", channels: "/channels", observability: "/observability", traces: "/traces",
    };
    if (routes[page]) navigate(routes[page]!);
  };
  return { sidebarCollapsed, setSidebarCollapsed, navigate, handleLogout, handleNavigate };
}

function Shell({ children, ...navigation }: { children: React.ReactNode } & ReturnType<typeof useVaultNavigation>) {
  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar active="vault" onNavigate={navigation.handleNavigate} onLogout={navigation.handleLogout} collapsed={navigation.sidebarCollapsed} onToggleCollapse={() => navigation.setSidebarCollapsed(!navigation.sidebarCollapsed)} agentCount={0} />
      <div className="flex min-w-0 flex-1 flex-col overflow-auto">{children}</div>
    </div>
  );
}

function KnowledgeOverview() {
  const navigation = useVaultNavigation();
  const [scopes, setScopes] = useState<KnowledgeScope[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listKnowledgeOverview()
      .then((overview) => setScopes(overview.scopes))
      .catch((reason) => setError(String(reason)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Shell {...navigation}>
      <PageHeader
        icon={Database}
        title="Knowledge Vault"
        description={loading ? "Loading…" : `${scopes.length} knowledge scope${scopes.length === 1 ? "" : "s"}`}
      />
      <main className="flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-6xl">
          {error && <p className="mb-4 text-sm text-[var(--danger)]">{error}</p>}
          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((item) => (
                <div key={item} className="h-[174px] animate-pulse rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--white)" }} />
              ))}
            </div>
          ) : scopes.length === 0 ? (
            <EmptyVaultState />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {scopes.map((scope) => (
                <KnowledgeScopeCard
                  key={scope.id}
                  scope={scope}
                  onClick={() => navigation.navigate(`/vault/${scope.id}`)}
                />
              ))}
            </div>
          )}
          <p className="mt-5 text-xs text-[var(--ink-3)]">
            Shared Knowledge is inherited by every agent. Agent-specific knowledge is available only to that agent.
          </p>
        </div>
      </main>
    </Shell>
  );
}

export function KnowledgeScopeCard({ scope, onClick }: { scope: KnowledgeScope; onClick: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => event.key === "Enter" && onClick()}
      className="group cursor-pointer rounded-[8px] border p-4 transition hover:border-[var(--accent)]"
      style={{ borderColor: "var(--border)", background: "var(--white)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="truncate text-[15px] font-semibold text-[var(--ink)]">{scope.name}</h2>
        <ArrowRight className="h-4 w-4 shrink-0 text-[var(--ink-3)] transition group-hover:text-[var(--accent)]" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
        <div>
          <p className="text-[10px] uppercase text-[var(--ink-3)]">Documents</p>
          <p className="font-semibold text-[var(--ink)]">{scope.document_count}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase text-[var(--ink-3)]">Chunks</p>
          <p className="font-semibold text-[var(--ink)]">{scope.chunk_count}</p>
        </div>
      </div>
    </div>
  );
}

function EmptyVaultState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl" style={{ background: "var(--accent-bg)" }}>
        <Database className="h-8 w-8" style={{ color: "var(--accent)" }} />
      </div>
      <h2 className="text-[20px] font-semibold text-[var(--ink)]">No knowledge scopes yet</h2>
      <p className="text-[13px] text-[var(--ink-2)]">Create an agent to add private knowledge, or use shared knowledge.</p>
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
    api.listKnowledgeScope(scope).then((response) => setDocuments(response.documents)).catch((reason) => setError(String(reason)));
  }, [scope]);

  const uploadFiles = async (files: FileList | File[]) => {
    setWorking(true); setUploading(true); setError("");
    try {
      for (const file of Array.from(files)) {
        const document = await api.uploadKnowledgeScope(scope, file);
        setDocuments((current) => [...current.filter((item) => item.id !== document.id), document].sort((a, b) => a.display_name.localeCompare(b.display_name)));
      }
    } catch (reason) { setError(String(reason)); } finally { setWorking(false); setUploading(false); }
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
    setWorking(true); setError("");
    try { setResults((await api.searchKnowledgeScope(scope, query.trim())).results); } catch (reason) { setError(String(reason)); } finally { setWorking(false); }
  };

  const reindex = async (document: KnowledgeDocument) => {
    setReindexing(document.id); setError("");
    try {
      const updated = await api.reindexKnowledgeDocument(scope, document.id);
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) { setError(String(reason)); } finally { setReindexing(null); }
  };

  const remove = async (document: KnowledgeDocument) => {
    const confirmed = await confirm({
      title: "Delete document",
      message: `Delete ${document.display_name}? This will remove it and its indexed chunks.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!confirmed) return;
    try { await api.deleteKnowledgeScope(scope, document.id); setDocuments((current) => current.filter((item) => item.id !== document.id)); } catch (reason) { setError(String(reason)); }
  };

  return (
    <Shell {...navigation}>
      <PageHeader
        icon={Database}
        title="Knowledge Vault"
        titleOnClick={() => navigation.navigate("/vault")}
        description={isShared ? "Available to every agent" : "Private agent knowledge"}
        breadcrumbs={[{ label: scopeName }]}
      />
      <main className="mx-auto w-full max-w-5xl space-y-5 px-8 py-7">
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <section className="rounded-lg border p-5" style={{ borderColor: "var(--border)", background: "var(--sidebar)" }}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-[var(--ink)]">Upload documents</h2>
            {uploading && <p role="status" className="text-xs text-[var(--accent)]">Uploading and indexing…</p>}
          </div>
          <p className="mt-1 text-xs text-[var(--ink-3)]">MD, TXT, PDF, DOCX, XLSX · up to 25 MB per file</p>
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
            className="mt-4 flex w-full cursor-pointer flex-col items-center rounded-md border border-dashed px-5 py-7 text-sm text-[var(--ink-2)] transition-colors hover:bg-[var(--surface)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              borderColor: dragActive ? "var(--accent)" : "var(--border)",
              background: dragActive ? "var(--accent-bg)" : undefined,
            }}
          >
            <Upload className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <span className="mt-2">Choose files or drag them here</span>
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".md,.markdown,.txt,.pdf,.docx,.xlsx"
            className="hidden"
            onChange={(event) => {
              if (event.target.files) void uploadFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </section>
        <section className="overflow-hidden rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--sidebar)" }}>
          <div className="border-b px-5 py-4" style={{ borderColor: "var(--border)" }}>
            <h2 className="text-sm font-semibold text-[var(--ink)]">Indexed documents</h2>
          </div>
          {documents.length === 0 ? <p className="px-5 py-8 text-sm text-[var(--ink-3)]">No documents indexed.</p> : (
            <table className="w-full text-left text-sm">
              <thead className="border-b text-[11px] uppercase tracking-wide text-[var(--ink-3)]" style={{ borderColor: "var(--border)" }}>
                <tr><th className="px-5 py-3 font-medium">Document</th><th className="px-5 py-3 font-medium">Status</th><th className="px-5 py-3 text-right font-medium">Actions</th></tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--border)" }}>
                {documents.map((document) => {
                  const structure = {
                    sections: document.structure?.sections ?? EMPTY_STRUCTURE.sections,
                    pages: document.structure?.pages ?? EMPTY_STRUCTURE.pages,
                    tables: document.structure?.tables ?? EMPTY_STRUCTURE.tables,
                    images: document.structure?.images ?? EMPTY_STRUCTURE.images,
                    sheets: document.structure?.sheets ?? EMPTY_STRUCTURE.sheets,
                  };
                  return (
                  <tr key={document.id}>
                    <td className="px-5 py-3"><div className="flex items-center gap-2"><FileText className="h-4 w-4" style={{ color: "var(--accent)" }} /><div><p className="text-[var(--ink)]">{document.display_name}</p><p className="text-xs text-[var(--ink-3)]">{document.source_path} · {formatBytes(document.size_bytes)}</p><p className="text-xs text-[var(--ink-3)]">{document.chunk_count ?? 0} chunks · {structure.sections.length} sections · {structure.pages.length} pages · {structure.tables.length} tables · {structure.images.length} images</p>{document.error && <p className="mt-1 text-xs text-[var(--danger)]">{document.error}</p>}</div></div></td>
                    <td className="px-5 py-3 text-xs text-[var(--accent)]">{document.status}</td>
                    <td className="px-5 py-3"><div className="flex justify-end gap-3"><button type="button" onClick={() => void reindex(document)} disabled={working || reindexing === document.id} className="cursor-pointer text-xs text-[var(--ink-2)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50">{reindexing === document.id ? "Indexing…" : "Re-index"}</button><button type="button" onClick={() => void remove(document)} aria-label={`Delete ${document.display_name}`} className="cursor-pointer text-[var(--ink-3)] hover:text-[var(--danger)]"><Trash2 className="h-4 w-4" /></button></div></td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
        <section className="rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--sidebar)" }}><div className="border-b px-5 py-4" style={{ borderColor: "var(--border)" }}><h2 className="text-sm font-semibold text-[var(--ink)]">Retrieval preview</h2><div className="mt-3 flex gap-3"><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void search()} placeholder="Search this scope…" className="min-w-0 flex-1 rounded-md border bg-transparent px-3 py-2 text-sm outline-none" style={{ borderColor: "var(--border)", color: "var(--ink)" }} /><button type="button" onClick={() => void search()} disabled={working || !query.trim()} className="flex cursor-pointer items-center gap-2 rounded-md border px-4 py-2 text-sm disabled:opacity-50" style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}><Search className="h-4 w-4" /> Search</button></div></div><div className="space-y-3 p-5">{results.length === 0 ? <p className="text-sm text-[var(--ink-3)]">Search results will appear here.</p> : results.map((result) => <article key={result.chunk_id} className="rounded-md border p-3" style={{ borderColor: "var(--border)" }}><p className="text-sm leading-6 text-[var(--ink)]">{result.text}</p><p className="mt-2 text-xs text-[var(--ink-3)]">{result.source_path}{result.page_number ? ` · page ${result.page_number}` : ""}{result.sheet_name ? ` · ${result.sheet_name}` : ""}</p></article>)}</div></section>
      </main>
    </Shell>
  );
}
