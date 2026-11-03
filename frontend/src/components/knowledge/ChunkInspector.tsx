import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { api } from "@/lib/api";
import type {
  KnowledgeChunk,
  KnowledgeChunksPage,
  KnowledgeDocument,
  KnowledgeRow,
  KnowledgeSheet,
} from "@/lib/types";

const PAGE_SIZE = 50;

interface Level {
  items: KnowledgeChunk[];
  cursor: string | null;
  loading: boolean;
  done: boolean;
}

const EMPTY_LEVEL: Level = { items: [], cursor: null, loading: false, done: false };

interface BranchState {
  /** Top level is keyed by "" ; branches by their parent chunk id. */
  levels: Record<string, Level>;
  expanded: Set<string>;
  corpusVersion: string | null;
  chunkCount: number;
  loading: boolean;
  stale: boolean;
  error: string | null;
}

const INITIAL: BranchState = {
  levels: {},
  expanded: new Set(),
  corpusVersion: null,
  chunkCount: 0,
  loading: true,
  stale: false,
  error: null,
};

function RowsView({
  scope,
  document,
}: {
  scope: string;
  document: KnowledgeDocument;
}) {
  const [sheets, setSheets] = useState<KnowledgeSheet[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [rows, setRows] = useState<KnowledgeRow[]>([]);
  const [columns, setColumns] = useState<{ id: string; label: string; kind: string }[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const alive = useRef(true);
  const activeSheet = useRef<string | null>(null);

  useEffect(() => {
    alive.current = true;
    api
      .listDocumentSheets(scope, document.id)
      .then((page) => {
        if (!alive.current) return;
        setSheets(page.sheets);
        if (page.sheets.length === 1) setActive(page.sheets[0].name);
      })
      .catch(() => alive.current && setSheets([]));
    return () => {
      alive.current = false;
    };
  }, [scope, document.id]);

  const load = useCallback(
    (sheet: string, next?: string) => {
      setLoading(true);
      setError(null);
      api
        .listDocumentRows(scope, document.id, {
          sheet,
          cursor: next,
          limit: 50,
        })
        .then((page) => {
          if (!alive.current || activeSheet.current !== sheet) return;
          setRows((prev) => (next ? [...prev, ...page.items] : page.items));
          setColumns(page.columns);
          setCursor(page.next_cursor);
          setStale(false);
        })
        .catch((err) => {
          if (!alive.current || activeSheet.current !== sheet) return;
          if (err?.status === 409) setStale(true);
          else setError(err?.message ?? "Could not load rows");
        })
        .finally(() => alive.current && setLoading(false));
    },
    [scope, document.id],
  );

  useEffect(() => {
    activeSheet.current = active;
    if (active) {
      setRows([]);
      setCursor(null);
      load(active);
    }
  }, [active, load]);

  if (sheets === null)
    return <p className="px-5 py-6 text-sm text-[var(--ink-faint)]">Loading sheets…</p>;
  if (sheets.length === 0)
    return (
      <p className="px-5 py-6 text-sm text-[var(--ink-faint)]">
        No parsed sheets — this document has no persisted row layer.
      </p>
    );

  const sheet = sheets.find((s) => s.name === active);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        {sheets.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setActive(s.name)}
            className="cursor-pointer rounded-md border px-3 py-1 text-xs"
            style={{
              borderColor: s.name === active ? "var(--accent)" : "var(--line)",
              color: s.name === active ? "var(--accent)" : "var(--ink-muted)",
            }}
          >
            {s.name} · {s.row_count} rows
          </button>
        ))}
      </div>
      {sheet?.warnings.map((w) => (
        <p key={w} className="px-5 pb-1 text-[11px] text-[var(--ink-faint)]">
          {w}
        </p>
      ))}
      {stale && (
        <div className="px-5 py-3">
          <p className="text-sm text-[var(--danger)]">
            This document was re-indexed — the view is stale.
          </p>
          <button
            type="button"
            onClick={() => active && load(active)}
            className="mt-1 cursor-pointer text-xs text-[var(--accent)] hover:underline"
          >
            Reload inspection
          </button>
        </div>
      )}
      {error && <p className="px-5 py-3 text-sm text-[var(--danger)]">{error}</p>}
      {!active ? (
        <p className="px-5 py-5 text-sm text-[var(--ink-faint)]">
          Choose a sheet to inspect its rows.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--line)" }}>
                <th className="px-3 py-2 font-medium text-[var(--ink-faint)]">row</th>
                {columns.map((c) => (
                  <th key={c.id} className="px-3 py-2 font-medium text-[var(--ink-faint)]">
                    {c.label}
                    <span className="ml-1 font-normal">({c.kind})</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--line)]">
              {rows.map((row) => (
                <tr key={row.row_number}>
                  <td
                    className="whitespace-nowrap px-3 py-1.5 text-[var(--ink-faint)]"
                    title={row.coord}
                  >
                    {row.row_number}
                  </td>
                  {columns.map((c) => (
                    <td
                      key={c.id}
                      className="max-w-56 truncate px-3 py-1.5 text-[var(--ink)]"
                    >
                      {row.cells[c.id] == null ? "" : String(row.cells[c.id])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {loading && (
            <p className="px-5 py-3 text-xs text-[var(--ink-faint)]">Loading…</p>
          )}
          {!loading && active && rows.length === 0 && (
            <p className="px-5 py-4 text-xs text-[var(--ink-faint)]">
              This sheet has no data rows.
            </p>
          )}
          {cursor && !loading && (
            <button
              type="button"
              onClick={() => load(active, cursor)}
              className="block w-full cursor-pointer px-5 py-2.5 text-left text-xs text-[var(--accent)] hover:underline"
            >
              Load more rows
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function ChunkInspector({
  scope,
  document,
  onClose,
}: {
  scope: string;
  document: KnowledgeDocument;
  onClose: () => void;
}) {
  const [state, setState] = useState<BranchState>(INITIAL);
  // Stale-response guard: only the latest document's fetches may write.
  const generation = useRef(0);

  const fetchLevel = useCallback(
    async (key: string, cursor?: string) => {
      const gen = generation.current;
      const page: KnowledgeChunksPage = await api.listDocumentChunks(
        scope,
        document.id,
        {
          parentId: key || undefined,
          cursor,
          limit: PAGE_SIZE,
        },
      );
      if (gen !== generation.current) return; // superseded selection
      setState((prev) => {
        const prior = prev.levels[key] ?? EMPTY_LEVEL;
        const items = cursor ? [...prior.items, ...page.items] : page.items;
        return {
          ...prev,
          loading: false,
          chunkCount: page.chunk_count,
          corpusVersion: page.corpus_version,
          levels: {
            ...prev.levels,
            [key]: {
              items,
              cursor: page.next_cursor,
              loading: false,
              done: !page.next_cursor,
            },
          },
        };
      });
    },
    [scope, document.id],
  );

  const loadLevel = useCallback(
    (key: string, cursor?: string) => {
      setState((prev) => ({
        ...prev,
        loading: !cursor && !prev.levels[key]?.items.length,
        error: null,
        stale: false,
        levels: {
          ...prev.levels,
          [key]: { ...(prev.levels[key] ?? EMPTY_LEVEL), loading: true },
        },
      }));
      fetchLevel(key, cursor).catch((err) => {
        if (generation.current !== undefined) {
          setState((prev) => ({
            ...prev,
            loading: false,
            stale: err?.status === 409,
            error:
              err?.status === 409
                ? null
                : (err?.message ?? "Could not load chunks"),
            levels: {
              ...prev.levels,
              [key]: {
                ...(prev.levels[key] ?? EMPTY_LEVEL),
                loading: false,
              },
            },
          }));
        }
      });
    },
    [fetchLevel],
  );

  useEffect(() => {
    generation.current += 1;
    setState(INITIAL);
    if (document.status === "indexed" || document.chunk_count) {
      loadLevel("");
    } else {
      setState({ ...INITIAL, loading: false });
    }
    return () => {
      generation.current += 1;
    };
  }, [document.id, document.status, document.chunk_count, loadLevel]);

  const toggle = (chunk: KnowledgeChunk) => {
    setState((prev) => {
      const expanded = new Set(prev.expanded);
      if (expanded.has(chunk.id)) {
        expanded.delete(chunk.id);
      } else {
        expanded.add(chunk.id);
      }
      return { ...prev, expanded };
    });
    if (!state.expanded.has(chunk.id) && !state.levels[chunk.id]) {
      loadLevel(chunk.id);
    }
  };

  const renderRows = (key: string, depth: number) => {
    const level = state.levels[key] ?? EMPTY_LEVEL;
    return (
      <>
        {level.items.map((chunk) => (
          <div key={chunk.id}>
            <div
              className="flex gap-2 border-b px-3 py-2"
              style={{ borderColor: "var(--line)", paddingLeft: 12 + depth * 18 }}
            >
              {chunk.has_children ? (
                <button
                  type="button"
                  aria-label={state.expanded.has(chunk.id) ? "Collapse" : "Expand"}
                  aria-expanded={state.expanded.has(chunk.id)}
                  onClick={() => toggle(chunk)}
                  className="mt-0.5 cursor-pointer text-[var(--ink-faint)] hover:text-[var(--ink)]"
                >
                  {state.expanded.has(chunk.id) ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                </button>
              ) : (
                <span className="w-3.5" />
              )}
              <div className="min-w-0 flex-1">
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--ink)]">
                  {chunk.preview}
                  {chunk.preview_truncated && (
                    <span className="text-[var(--ink-faint)]"> …</span>
                  )}
                </p>
                <p className="mt-1 text-[10px] text-[var(--ink-faint)]">
                  #{chunk.seq} · {chunk.kind}
                  {chunk.block_type ? ` · ${chunk.block_type}` : ""}
                  {chunk.page_number != null ? ` · p.${chunk.page_number}` : ""}
                  {chunk.source_location ? ` · ${chunk.source_location}` : ""}
                  {chunk.token_count != null
                    ? ` · ${chunk.token_count} tokens`
                    : ""}
                  {chunk.heading_path.length > 0
                    ? ` · ${chunk.heading_path.join(" › ")}`
                    : ""}
                </p>
              </div>
            </div>
            {state.expanded.has(chunk.id) && renderRows(chunk.id, depth + 1)}
          </div>
        ))}
        {level.loading && (
          <p className="px-5 py-2 text-xs text-[var(--ink-faint)]">Loading…</p>
        )}
        {level.cursor && !level.loading && (
          <button
            type="button"
            onClick={() => loadLevel(key, level.cursor ?? undefined)}
            className="block w-full cursor-pointer px-5 py-2 text-left text-xs text-[var(--accent)] hover:underline"
          >
            Load more
          </button>
        )}
      </>
    );
  };

  return (
    <section
      className="overflow-hidden rounded-xl"
      style={{ border: "1px solid var(--line)", background: "var(--surface)" }}
    >
      <div
        className="flex items-center justify-between border-b px-5 py-3"
        style={{ borderColor: "var(--line)" }}
      >
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-[var(--ink)]">
            {document.display_name}
          </h2>
          <p className="text-[11px] text-[var(--ink-faint)]">
            {state.chunkCount} persisted chunks · hash{" "}
            {document.content_hash.slice(0, 12)}
            {state.corpusVersion
              ? ` · corpus ${state.corpusVersion.slice(-19)}`
              : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close inspection"
          className="cursor-pointer text-[var(--ink-faint)] hover:text-[var(--ink)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="max-h-[28rem] overflow-y-auto">
        {/csv|spreadsheet/.test(document.mime_type) &&
        document.status === "indexed" ? (
          <RowsView scope={scope} document={document} />
        ) : (
          <>
        {document.status === "pending" && (
          <p className="px-5 py-6 text-sm text-[var(--ink-faint)]">
            Still indexing — chunks appear here once persisted.
          </p>
        )}
        {document.status === "failed" && (
          <p className="px-5 py-6 text-sm text-[var(--danger)]">
            Indexing failed{document.error ? `: ${document.error}` : "."}
          </p>
        )}
        {state.stale && (
          <div className="px-5 py-4">
            <p className="text-sm text-[var(--danger)]">
              This document was re-indexed — the view is stale.
            </p>
            <button
              type="button"
              onClick={() => loadLevel("")}
              className="mt-2 cursor-pointer text-xs text-[var(--accent)] hover:underline"
            >
              Reload inspection
            </button>
          </div>
        )}
        {state.error && !state.stale && (
          <p className="px-5 py-4 text-sm text-[var(--danger)]">{state.error}</p>
        )}
        {document.status === "indexed" &&
          !state.loading &&
          !state.stale &&
          !state.error &&
          (state.levels[""]?.items.length ?? 0) === 0 && (
            <p className="px-5 py-6 text-sm text-[var(--ink-faint)]">
              Indexed, but no chunks were persisted for this document.
            </p>
          )}
        {state.loading &&
          (state.levels[""]?.items.length ?? 0) === 0 &&
          document.status === "indexed" && (
            <p className="px-5 py-6 text-sm text-[var(--ink-faint)]">
              Loading chunks…
            </p>
          )}
        {!state.stale && renderRows("", 0)}
          </>
        )}
      </div>
    </section>
  );
}
