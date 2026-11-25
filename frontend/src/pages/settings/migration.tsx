import { useState } from "react";
import {
  Check,
  Download,
  HardDrive,
  Info,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { useDesktopFileDrop } from "@/lib/desktopFileDrop";
import { resetGuidance } from "@/components/guidance/guidanceState";

interface ImportResult {
  status: string;
  mode: string;
  imported_files?: number;
  rows_added?: number;
  rows_skipped?: number;
  files_added?: number;
  tables_merged?: string[];
  secret_keys_match?: boolean;
  warnings?: string[];
  message: string;
}

interface PreviewTable {
  table: string;
  imported_count: number;
  target_count: number;
  new_in_merge: number;
}

interface PreviewResult {
  status: string;
  tables: PreviewTable[];
  agent_files: number;
  workspace_files: number;
  has_secret_key: boolean;
  secret_keys_match: boolean | null;
}

export function MigrationTab() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const { confirm, toast } = useConfirm();

  const handleExport = async () => {
    setBusy(true);
    try {
      const resp = await fetch(`${api.baseURL}/api/data/export`, {
        credentials: "include",
        headers: api.authHeaders(),
      });
      if (!resp.ok) throw new Error("Export failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `caberos-backup-${Date.now()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Export downloaded");
    } catch {
      toast("Export failed");
    } finally {
      setBusy(false);
    }
  };

  // Single entry point: pick or drop a file -> auto-preview -> choose action
  const startPreview = async (file: File) => {
    setSelectedFile(file);
    setPreview(null);
    setResult(null);
    setBusy(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const resp = await fetch(`${api.baseURL}/api/data/preview`, {
        method: "POST",
        credentials: "include",
        headers: api.authHeaders(),
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        toast(`Preview failed: ${err.detail || "unknown error"}`);
        setSelectedFile(null);
      } else {
        setPreview(await resp.json());
      }
    } catch (err) {
      toast(`Preview failed: ${err}`);
      setSelectedFile(null);
    } finally {
      setBusy(false);
    }
  };

  const handlePickFile = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) void startPreview(file);
    };
    input.click();
  };

  // One entry for DOM drops and native Tauri drops — validate + busy guard.
  const acceptDroppedFiles = (files: File[]) => {
    if (busy) return;
    const file = files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      toast("Import expects a .zip archive from Export");
      return;
    }
    void startPreview(file);
  };

  // Native Tauri file drops bypass DOM drag events — the webview takes them.
  useDesktopFileDrop({
    onFiles: acceptDroppedFiles,
    onDraggingChange: (d) => setDragActive(d && !busy),
    onError: () => toast("Could not read the dropped file"),
  });

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    acceptDroppedFiles(Array.from(e.dataTransfer.files ?? []));
  };

  const handleImport = (importMode: "replace" | "merge") => {
    if (!selectedFile) return;
    const doImport = async () => {
      const confirmed = await confirm({
        title: importMode === "replace" ? "Replace All Data?" : "Merge Data?",
        message:
          importMode === "replace"
            ? "This will WIPE all current data (agents, providers, MCP, channels, sessions, memory) and restore everything from the archive. This cannot be undone."
            : "This will add new data from the archive into the current instance. Existing data is kept. Encrypted credentials only work if both instances share the same secret key.",
        confirmLabel: importMode === "replace" ? "Wipe & Restore" : "Merge",
        cancelLabel: "Cancel",
        danger: importMode === "replace",
      });
      if (!confirmed) return;

      setBusy(true);
      setResult(null);
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("mode", importMode);
      try {
        const resp = await fetch(`${api.baseURL}/api/data/import`, {
          method: "POST",
          credentials: "include",
          headers: api.authHeaders(),
          body: formData,
        });
        if (!resp.ok) {
          const err = await resp.json();
          toast(`Import failed: ${err.detail || "unknown error"}`);
        } else {
          const res = (await resp.json()) as ImportResult;
          setResult(res);
          toast(
            importMode === "replace"
              ? "Data replaced — restart the server"
              : "Data merged — restart the server",
          );
        }
      } catch (err) {
        toast(`Import failed: ${err}`);
      } finally {
        setBusy(false);
      }
    };
    doImport();
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
  };

  const handleDeleteAll = async () => {
    const confirmed = await confirm({
      title: "Delete all CaberOS data?",
      message:
        "This permanently deletes agents, providers, MCP credentials, channels, sessions, memory, workspaces, attachments, and restore points. This cannot be undone.",
      confirmLabel: "Delete everything",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.deleteAllData();
      resetGuidance();
      localStorage.removeItem("agentos_session_token");
      window.location.assign("/login");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete all data");
      setBusy(false);
    }
  };

  const step = !selectedFile ? 1 : result ? 3 : preview ? 3 : 2;
  const STEPS = [
    { n: 1, title: "Choose an archive", sub: "A .zip from Export" },
    { n: 2, title: "Review", sub: "See what's inside" },
    { n: 3, title: "Merge or replace", sub: "Merge keeps your data" },
  ];

  return (
    <div className="max-w-4xl space-y-8">
      {/* Export */}
      <section id="export">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Export</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Back up or move your workspace.
        </p>
        <div
          className="flex gap-8 rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="min-w-0 flex-1">
            <p className="text-[13px] text-[var(--ink-2)]">
              Save everything to one ZIP archive. Import it on another instance,
              for example web to desktop, to bring it all across.
            </p>
            <button
              onClick={handleExport}
              disabled={busy}
              className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: "var(--ink)", color: "var(--white)" }}
            >
              <Download className="h-3.5 w-3.5" />
              Export data
            </button>
          </div>
          <div
            className="w-56 shrink-0 border-l pl-5"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">
              Included
            </p>
            <ul className="space-y-1.5">
              {[
                "Agents and versioned configs",
                "Providers and encrypted API keys",
                "MCP servers and channels",
                "Sessions, messages and memory",
                "Workspace files",
                "Secret key (credential decryption)",
              ].map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-1.5 text-[12px] text-[var(--ink-2)]"
                >
                  <Check className="h-3 w-3 shrink-0 text-[var(--accent)]" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Import — pick file -> preview -> merge/replace */}
      <section id="import">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Import</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Bring in an archive from another CaberOS.
        </p>
        <div
          className="rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          {/* Stepper */}
          <div className="mb-5 flex items-start">
            {STEPS.map((s, i) => (
              <div
                key={s.n}
                className={`flex items-start gap-2.5 ${i < STEPS.length - 1 ? "flex-1" : ""}`}
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                  style={{
                    background:
                      s.n <= step ? "var(--accent)" : "var(--border-soft)",
                    color: s.n <= step ? "var(--white)" : "var(--ink-3)",
                  }}
                >
                  {s.n < step ? <Check className="h-3 w-3" /> : s.n}
                </span>
                <span className="min-w-0">
                  <span
                    className="block text-[12px] font-semibold"
                    style={{
                      color: s.n <= step ? "var(--ink)" : "var(--ink-3)",
                    }}
                  >
                    {s.title}
                  </span>
                  <span className="block text-[11px] text-[var(--ink-3)]">
                    {s.sub}
                  </span>
                </span>
                {i < STEPS.length - 1 && (
                  <span
                    className="mx-4 mt-3 h-px flex-1"
                    style={{ background: "var(--border)" }}
                  />
                )}
              </div>
            ))}
          </div>

          {/* Step 1: Pick or drop file */}
          {!selectedFile && !result && (
            <button
              onClick={handlePickFile}
              onDragOver={(e) => {
                e.preventDefault();
                if (!busy) setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              disabled={busy}
              className="flex w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-10 text-center transition"
              style={{
                borderColor: dragActive
                  ? "var(--accent)"
                  : "color-mix(in srgb, var(--accent) 45%, var(--border))",
                background: dragActive ? "var(--accent-bg)" : "var(--surface)",
                cursor: busy ? "default" : "pointer",
              }}
            >
              <Upload
                className="mb-1 h-5 w-5"
                style={{ color: "var(--accent)" }}
              />
              <span className="text-[13px] font-semibold text-[var(--ink)]">
                {busy
                  ? "Analyzing archive…"
                  : "Choose a .zip archive to import"}
              </span>
              <span className="text-[12px] text-[var(--ink-3)]">
                or drop it here
              </span>
            </button>
          )}

          {/* Step 2/3: Preview + action buttons */}
          {selectedFile && !result && (
            <div className="space-y-4">
              {/* Selected file */}
              <div
                className="flex items-center justify-between rounded-lg border px-3 py-2"
                style={{ borderColor: "var(--border-soft)" }}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <HardDrive className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                  <span className="truncate text-[13px] font-semibold text-[var(--ink)]">
                    {selectedFile.name}
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--ink-3)]">
                    {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                </div>
                <button
                  onClick={handleReset}
                  disabled={busy}
                  className="flex shrink-0 items-center gap-1 text-[11px] text-[var(--ink-3)] transition hover:text-[var(--ink)]"
                  style={{ cursor: busy ? "default" : "pointer" }}
                >
                  <X className="h-3 w-3" />
                  Change file
                </button>
              </div>

              {/* Loading state */}
              {busy && !preview && (
                <div className="flex items-center gap-2 text-[12px] text-[var(--ink-3)]">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  Analyzing archive…
                </div>
              )}

              {/* Preview results */}
              {preview && (
                <div
                  className="overflow-hidden rounded-xl border"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  {/* Secret key indicator */}
                  <div
                    className="flex items-center gap-1.5 border-b px-4 py-2.5 text-[12px]"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    {preview.secret_keys_match === true ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
                        <span className="text-[var(--ink-2)]">
                          Secret keys match — credentials will decrypt
                        </span>
                      </>
                    ) : preview.secret_keys_match === false ? (
                      <>
                        <Info className="h-3.5 w-3.5 text-[var(--danger)]" />
                        <span className="text-[var(--danger)]">
                          Secret keys differ — credentials won't decrypt after
                          merge
                        </span>
                      </>
                    ) : (
                      <span className="text-[var(--ink-3)]">
                        No secret key in archive
                      </span>
                    )}
                  </div>

                  {/* Table breakdown */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr
                          className="border-b text-[11px] font-medium text-[var(--ink-3)]"
                          style={{ borderColor: "var(--border-soft)" }}
                        >
                          <th className="py-2 pl-4 pr-4 text-left font-medium">
                            Table
                          </th>
                          <th className="px-4 py-2 text-right font-medium">
                            In archive
                          </th>
                          <th className="px-4 py-2 text-right font-medium">
                            Current
                          </th>
                          <th className="py-2 pl-4 pr-4 text-right font-medium">
                            New (merge)
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.tables.map((t) => (
                          <tr
                            key={t.table}
                            className="border-b last:border-0"
                            style={{ borderColor: "var(--border-soft)" }}
                          >
                            <td className="py-2 pl-4 pr-4 font-mono text-[var(--ink)]">
                              {t.table}
                            </td>
                            <td className="px-4 py-2 text-right text-[var(--ink-2)]">
                              {t.imported_count}
                            </td>
                            <td className="px-4 py-2 text-right text-[var(--ink-2)]">
                              {t.target_count}
                            </td>
                            <td className="py-2 pl-4 pr-4 text-right">
                              <span
                                style={{
                                  color:
                                    t.new_in_merge > 0
                                      ? "var(--accent)"
                                      : "var(--ink-3)",
                                }}
                              >
                                {t.new_in_merge > 0
                                  ? `+${t.new_in_merge}`
                                  : "0"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* File counts */}
                  <div
                    className="flex gap-4 border-t px-4 py-2.5 text-[12px] text-[var(--ink-3)]"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <span>{preview.agent_files} agent files</span>
                    <span>{preview.workspace_files} workspace files</span>
                    {preview.has_secret_key && <span>includes secret.key</span>}
                  </div>
                </div>
              )}

              {/* Action buttons — only after preview loads */}
              {preview && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {/* Merge */}
                  <div
                    className="rounded-xl border p-4"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-[var(--ink)]">
                        Merge
                      </span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{
                          background: "var(--accent-bg)",
                          color: "var(--accent)",
                        }}
                      >
                        Recommended
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                      Keep existing data, add new items from the archive.
                    </p>
                    <button
                      onClick={() => handleImport("merge")}
                      disabled={busy}
                      className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                      style={{
                        background: "var(--ink)",
                        color: "var(--white)",
                      }}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      Merge import
                    </button>
                  </div>

                  {/* Replace */}
                  <div
                    className="rounded-xl border p-4"
                    style={{
                      borderColor:
                        "color-mix(in srgb, var(--danger) 45%, transparent)",
                      background:
                        "color-mix(in srgb, var(--danger) 5%, transparent)",
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-[var(--ink)]">
                        Replace
                      </span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{
                          background:
                            "color-mix(in srgb, var(--danger) 14%, transparent)",
                          color: "var(--danger)",
                        }}
                      >
                        Destructive
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                      Wipe all current data, restore from archive.
                    </p>
                    <button
                      onClick={() => handleImport("replace")}
                      disabled={busy}
                      className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                      style={{
                        borderColor: "var(--danger)",
                        color: "var(--danger)",
                      }}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      Replace import
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Import result */}
          {result && (
            <div>
              <div
                className="rounded-xl border p-4"
                style={{
                  borderColor: result.warnings?.length
                    ? "color-mix(in srgb, var(--danger) 45%, transparent)"
                    : "var(--border-soft)",
                  background: result.warnings?.length
                    ? "color-mix(in srgb, var(--danger) 5%, transparent)"
                    : "var(--surface)",
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Check className="h-4 w-4 text-[var(--accent)]" />
                    <span className="text-[13px] font-semibold text-[var(--ink)]">
                      Import {result.mode === "replace" ? "Replace" : "Merge"}{" "}
                      Complete
                    </span>
                  </div>
                  <button
                    onClick={handleReset}
                    className="flex items-center gap-1 text-[11px] text-[var(--ink-3)] transition hover:text-[var(--ink)]"
                  >
                    <X className="h-3 w-3" />
                    Done
                  </button>
                </div>

                {/* Replace mode stats */}
                {result.mode === "replace" && result.imported_files != null && (
                  <div className="mt-2 text-[12px] text-[var(--ink-2)]">
                    {result.imported_files} files restored from archive
                  </div>
                )}

                {/* Merge mode stats */}
                {result.mode === "merge" && (
                  <div className="mt-2 space-y-1.5 text-[12px] text-[var(--ink-2)]">
                    <div className="flex gap-4">
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.rows_added ?? 0}
                        </strong>{" "}
                        rows added
                      </span>
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.rows_skipped ?? 0}
                        </strong>{" "}
                        rows skipped (already exist)
                      </span>
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.files_added ?? 0}
                        </strong>{" "}
                        files added
                      </span>
                    </div>

                    {result.tables_merged &&
                      result.tables_merged.length > 0 && (
                        <div className="mt-2">
                          <span className="text-[var(--ink-3)]">
                            Tables updated:
                          </span>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {result.tables_merged.map((t) => (
                              <span
                                key={t}
                                className="rounded-full px-2 py-0.5 text-[10px] font-mono"
                                style={{
                                  background: "var(--accent-bg)",
                                  color: "var(--accent)",
                                }}
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Secret key match indicator */}
                    {result.secret_keys_match != null && (
                      <div className="mt-2 flex items-center gap-1.5">
                        {result.secret_keys_match ? (
                          <>
                            <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
                            <span className="text-[var(--ink-3)]">
                              Secret keys match — credentials will decrypt
                              correctly
                            </span>
                          </>
                        ) : (
                          <>
                            <Info className="h-3.5 w-3.5 text-[var(--danger)]" />
                            <span className="text-[var(--danger)]">
                              Secret keys differ — re-enter credentials in the
                              target instance
                            </span>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Warnings */}
                {result.warnings && result.warnings.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {result.warnings.map((w, i) => (
                      <p key={i} className="text-[12px] text-[var(--danger)]">
                        ⚠ {w}
                      </p>
                    ))}
                  </div>
                )}

                <p className="mt-3 text-[11px] font-medium text-[var(--ink)]">
                  Restart the server for changes to take effect.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Danger zone */}
      <section id="danger-zone">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Danger zone
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Actions you can't take back.
        </p>
        <div
          className="flex items-center justify-between gap-6 rounded-xl p-5"
          style={{
            border: "1px solid var(--danger)",
            background: "var(--surface)",
          }}
        >
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-[var(--danger)]">
              Delete all data
            </p>
            <p className="mt-1 text-[12px] text-[var(--ink-2)]">
              Removes all local CaberOS data and returns to the first-run setup.
              Export first if you might need it again. This cannot be undone.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleDeleteAll()}
            disabled={busy}
            className="shrink-0 rounded-lg border px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
            style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
          >
            Delete all data…
          </button>
        </div>
      </section>
    </div>
  );
}

