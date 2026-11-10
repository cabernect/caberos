import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Folder, Loader2, X } from "lucide-react";
import { api } from "@/lib/api";

interface DirPage {
  path: string;
  parent: string | null;
  directories: { name: string; path: string }[];
  truncated: boolean;
}

/** Server-side folder picker — the backend runs locally, so the browser
 *  UI can offer a real directory chooser. Directory names only. */
export function FolderPicker({
  initialPath,
  title = "Choose workspace folder",
  onPick,
  onClose,
}: {
  initialPath?: string;
  title?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const [page, setPage] = useState<DirPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const alive = useRef(true);

  const browse = useCallback((path?: string) => {
    setLoading(true);
    setError(null);
    setFilter("");
    api
      .listDirectories(path, true)
      .then((p) => alive.current && setPage(p))
      .catch((e) => alive.current && setError(e?.message ?? "Cannot read folder"))
      .finally(() => alive.current && setLoading(false));
  }, []);

  useEffect(() => {
    alive.current = true;
    browse(initialPath || undefined);
    return () => {
      alive.current = false;
    };
  }, [browse, initialPath]);

  const dirs = (page?.directories ?? []).filter((d) =>
    d.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      role="dialog"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="flex max-h-[70vh] w-[28rem] max-w-[92vw] flex-col overflow-hidden rounded-xl border"
        style={{ background: "var(--surface)", borderColor: "var(--line)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between border-b px-4 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          <h3 className="text-sm font-semibold text-[var(--ink)]">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="cursor-pointer text-[var(--ink-faint)] hover:text-[var(--ink)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div
          className="flex items-center gap-2 border-b px-4 py-2"
          style={{ borderColor: "var(--line)" }}
        >
          {page?.parent && (
            <button
              type="button"
              onClick={() => browse(page.parent ?? undefined)}
              aria-label="Up one level"
              className="cursor-pointer text-[var(--ink-faint)] hover:text-[var(--ink)]"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--ink-muted)]">
            {page?.path ?? "…"}
          </span>
        </div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter folders…"
          className="border-b bg-transparent px-4 py-2 text-xs outline-none"
          style={{ borderColor: "var(--line)", color: "var(--ink)" }}
        />
        <div className="min-h-40 flex-1 overflow-y-auto py-1">
          {loading && (
            <p className="flex items-center gap-2 px-4 py-6 text-xs text-[var(--ink-faint)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </p>
          )}
          {error && <p className="px-4 py-4 text-xs text-[var(--danger)]">{error}</p>}
          {!loading && !error && dirs.length === 0 && (
            <p className="px-4 py-6 text-xs text-[var(--ink-faint)]">
              No subfolders here — pick this folder or go up.
            </p>
          )}
          {!loading &&
            !error &&
            dirs.map((d) => (
              <button
                key={d.path}
                type="button"
                onClick={() => browse(d.path)}
                className="flex w-full cursor-pointer items-center gap-2 px-4 py-1.5 text-left text-xs text-[var(--ink)] hover:bg-[var(--sunken)]"
              >
                <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                <span className="truncate">{d.name}</span>
              </button>
            ))}
          {page?.truncated && (
            <p className="px-4 py-1.5 text-[10px] text-[var(--ink-faint)]">
              Folder list truncated — use the path field for deep locations.
            </p>
          )}
        </div>
        <div
          className="flex justify-end gap-2 border-t px-4 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          <button
            type="button"
            onClick={onClose}
            className="cursor-pointer rounded-md border px-3 py-1.5 text-xs text-[var(--ink-muted)]"
            style={{ borderColor: "var(--line)" }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!page}
            onClick={() => page && onPick(page.path)}
            className="cursor-pointer rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            Use this folder
          </button>
        </div>
      </div>
    </div>
  );
}

/** Pick a folder natively on Tauri, else via the server-side picker. */
export function isDesktopShell(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Native folder selection: Tauri dialog in the desktop shell, else the
 *  backend's OS dialog (osascript/zenity/FolderBrowserDialog).
 *  Returns the path, null when cancelled, or "unsupported" → open the
 *  server-side picker instead. */
export async function pickFolderNative(
  title = "Choose workspace folder",
): Promise<string | null | "unsupported"> {
  if (isDesktopShell()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const picked = await open({ directory: true, title });
    return typeof picked === "string" ? picked : null;
  }
  try {
    const result = await api.pickDirectory();
    return result.path;
  } catch {
    return "unsupported";
  }
}
