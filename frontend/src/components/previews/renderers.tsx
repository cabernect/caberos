import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, FileWarning, Loader2, Maximize2, Minimize2, ZoomIn, ZoomOut } from "lucide-react";
import type { PreviewBackend, PreviewSource } from "@/lib/api";
import type { PreviewElement, PreviewPayload } from "@/lib/types";
import { Markdown } from "@/components/Markdown";
import { readView, viewStateKey, writeView } from "./viewState";
import { useObjectUrl } from "./useObjectUrl";

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/** Dispatch table — every backend kind maps to exactly one renderer. */
export function PreviewBody({
  payload,
  backend,
  source,
  expanded,
  onFocus,
}: {
  payload: PreviewPayload;
  backend: PreviewBackend;
  source: PreviewSource;
  /** Expanded modal mode — visual kinds render larger. */
  expanded?: boolean;
  /** Reports the operator's current focus inside paged content
   *  ("slide 3 of 12", sheet name) so the panel can target revise requests. */
  onFocus?: (label: string | null) => void;
}) {
  if (payload.error && !payload.elements?.length && !payload.slides?.length) {
    return <Note text={payload.error} />;
  }
  switch (payload.kind) {
    case "markdown":
      return <MarkdownView content={payload.content || ""} truncated={payload.truncated} />;
    case "code":
    case "json":
    case "text":
      return (
        <TextView
          content={payload.content || ""}
          truncated={payload.truncated}
          language={payload.language}
        />
      );
    case "table":
      return (
        <TableView
          header={payload.header || []}
          rows={payload.rows || []}
          truncated={payload.truncated}
          totalRows={payload.total_rows}
        />
      );
    case "image":
      return <ImageView backend={backend} source={source} name={payload.name} expanded={expanded} />;
    case "pdf":
      return <PdfView backend={backend} source={source} pageCount={payload.page_count || 0} expanded={expanded} />;
    case "document":
      return <ElementsView elements={payload.elements || []} />;
    case "slides":
      return <SlidesView payload={payload} onFocus={onFocus} />;
    case "workbook":
      return <WorkbookView payload={payload} onFocus={onFocus} />;
    case "deck":
      return <DeckView payload={payload} backend={backend} source={source} onFocus={onFocus} />;
    case "media":
      return (
        <MediaView backend={backend} source={source} media={payload.media || "audio"} expanded={expanded} />
      );
    default:
      return <UnknownView payload={payload} />;
  }
}

function Note({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-3 text-[12px] text-[var(--ink-2)]">
      <FileWarning className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

function TruncatedFlag() {
  return (
    <p className="mt-2 text-[11px] italic text-[var(--ink-3)]">
      Preview truncated — download the file for the full contents.
    </p>
  );
}

function MarkdownView({ content, truncated }: { content: string; truncated?: boolean }) {
  const [showSource, setShowSource] = useState(false);
  return (
    <div>
      <div className="mb-2 flex gap-1 text-[11px]">
        {(["rendered", "source"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setShowSource(m === "source")}
            className="rounded-[4px] px-2 py-0.5 capitalize transition-colors"
            style={{
              background: (m === "source") === showSource ? "var(--accent)" : "var(--surface)",
              color: (m === "source") === showSource ? "var(--white)" : "var(--ink-2)",
              border: "1px solid var(--border)",
              cursor: "pointer",
            }}
          >
            {m}
          </button>
        ))}
      </div>
      {showSource ? (
        <pre className="overflow-auto whitespace-pre-wrap font-mono text-[12px] leading-[1.6] text-[var(--ink)]">
          {content}
        </pre>
      ) : (
        <div className="markdown-body max-w-none text-[13px] text-[var(--ink)]">
          <Markdown>{content}</Markdown>
        </div>
      )}
      {truncated && <TruncatedFlag />}
    </div>
  );
}

function TextView({
  content,
  truncated,
  language,
}: {
  content: string;
  truncated?: boolean;
  language?: string;
}) {
  return (
    <div>
      {language && (
        <span className="mb-2 inline-block rounded-[4px] border border-[var(--border)] bg-[var(--surface)] px-1.5 py-0.5 font-mono text-[10px] uppercase text-[var(--ink-3)]">
          {language}
        </span>
      )}
      <pre className="overflow-auto whitespace-pre-wrap rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-3 font-mono text-[12px] leading-[1.6] text-[var(--ink)]">
        {content}
      </pre>
      {truncated && <TruncatedFlag />}
    </div>
  );
}

function TableView({
  header,
  rows,
  truncated,
  totalRows,
}: {
  header: unknown[];
  rows: unknown[][];
  truncated?: boolean;
  totalRows?: number;
}) {
  return (
    <div>
      <GridTable header={header} rows={rows} />
      {truncated && (
        <p className="mt-2 text-[11px] italic text-[var(--ink-3)]">
          Showing {rows.length.toLocaleString()}
          {totalRows != null ? ` of ${totalRows.toLocaleString()}` : ""} rows —
          download the file for the full contents.
        </p>
      )}
    </div>
  );
}

export function GridTable({ header, rows }: { header: unknown[]; rows: unknown[][] }) {
  return (
    <div className="overflow-auto rounded-[5px] border border-[var(--border)]">
      <table className="w-full border-collapse text-[12px]">
        {header.length > 0 && (
          <thead>
            <tr className="bg-[var(--surface)]">
              {header.map((h, i) => (
                <th
                  key={i}
                  className="border-b border-[var(--border)] px-2.5 py-1.5 text-left font-medium text-[var(--ink-2)]"
                >
                  {String(h ?? "")}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-[var(--surface)]/50" : ""}>
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="border-b border-[var(--border)]/50 px-2.5 py-1.5 font-mono text-[var(--ink)]"
                >
                  {cell === null || cell === undefined ? "" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageView({
  backend,
  source,
  name,
  expanded,
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  name: string;
  expanded?: boolean;
}) {
  const { url, loading, error } = useObjectUrl(
    () => backend.blob(source),
    [backend, source.path, source.artifactId, source.revisionId],
  );
  if (error) return <Note text={error} />;
  if (loading || !url) return <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />;
  return (
    <img
      src={url}
      alt={name}
      className={`${expanded ? "max-h-[82vh]" : "max-h-[70vh]"} max-w-full rounded-[5px] border border-[var(--border)] object-contain`}
    />
  );
}

function PdfView({
  backend,
  source,
  pageCount,
  expanded,
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  pageCount: number;
  expanded?: boolean;
}) {
  const [page, setPage] = useState(1);
  const { url, loading, error } = useObjectUrl(
    () => backend.pdfPage(page, source),
    [backend, page, source.path, source.artifactId, source.revisionId],
  );
  if (pageCount === 0) return <Note text="No pages to render." />;
  return (
    <div className={expanded ? "flex flex-col items-center" : ""}>
      <div className="mb-2 flex items-center gap-2 text-[12px] text-[var(--ink-2)]">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="font-mono">
          {page} / {pageCount}
        </span>
        <button
          onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          disabled={page >= pageCount}
          className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
          aria-label="Next page"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      {error ? (
        <Note text={error} />
      ) : loading || !url ? (
        <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />
      ) : (
        <img
          src={url}
          alt={`Page ${page}`}
          className={`${expanded ? "max-h-[80vh]" : "max-h-[70vh]"} max-w-full rounded-[5px] border border-[var(--border)]`}
        />
      )}
    </div>
  );
}

/** The shared W2 element vocabulary — one renderer for docx + slide content. */
export function ElementsView({ elements }: { elements: PreviewElement[] }) {
  // Consecutive images render as a wrap grid — real decks pack logos/icons/
  // decorations that look broken when stacked as full-width empty boxes.
  const items: ReactNode[] = [];
  for (let i = 0; i < elements.length; i++) {
    if (elements[i].type === "image") {
      const run: PreviewElement[] = [];
      while (i < elements.length && elements[i].type === "image") {
        run.push(elements[i]);
        i++;
      }
      i--;
      items.push(
        <div key={`imgs-${i}`} className="flex flex-wrap items-start gap-2">
          {run.map((el, j) =>
            el.data_url ? (
              <img
                key={j}
                src={el.data_url}
                alt=""
                className="max-h-44 max-w-[45%] rounded-[5px] border border-[var(--border)] object-contain"
              />
            ) : null
          )}
        </div>
      );
      continue;
    }
    items.push(renderElement(elements[i], i));
  }
  return (
    <div className="space-y-2 text-[13px] text-[var(--ink)]">
      {items}
      {elements.length === 0 && <p className="text-[var(--ink-3)]">Empty document.</p>}
    </div>
  );
}

function renderElement(el: PreviewElement, i: number): ReactNode {
  switch (el.type) {
          case "heading": {
            const level = el.level || 1;
            const cls =
              level <= 1
                ? "text-[18px] font-semibold"
                : level === 2
                  ? "text-[15px] font-semibold"
                  : "text-[13px] font-semibold";
            return (
              <div key={i} className={`${cls} pt-1 text-[var(--ink)]`}>
                {el.text}
              </div>
            );
          }
          case "paragraph":
            return (
              <p key={i} className="leading-[1.6]">
                {el.text}
              </p>
            );
          case "list":
            return el.style === "number" ? (
              <ol key={i} className="list-decimal space-y-0.5 pl-5">
                {(el.items || []).map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ol>
            ) : (
              <ul key={i} className="list-disc space-y-0.5 pl-5">
                {(el.items || []).map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ul>
            );
          case "table":
            return (
              <GridTable key={i} header={el.header || []} rows={(el.rows || []) as unknown[][]} />
            );
          case "image":
            return el.data_url ? (
              <img
                key={i}
                src={el.data_url}
                alt=""
                className="max-h-64 max-w-full rounded-[5px] border border-[var(--border)] object-contain"
              />
            ) : null;
          case "chart":
            // Charts render as honest data tables — no chart lib dependency.
            return (
              <div key={i}>
                <GridTable
                  header={["", ...(el.series || []).map((s) => s.name)]}
                  rows={(el.categories || []).map((cat, ci) => [
                    cat,
                    ...(el.series || []).map((s) => s.values[ci]),
                  ])}
                />
              </div>
            );
          case "notes":
            return (
              <p key={i} className="border-l-2 border-[var(--border)] pl-2 text-[12px] italic text-[var(--ink-3)]">
                {el.text}
              </p>
            );
          case "page_break":
            return <hr key={i} className="border-[var(--border)]" />;
          default:
            return null;
  }
}

function SlidesView({
  payload,
  onFocus,
}: {
  payload: PreviewPayload;
  onFocus?: (label: string | null) => void;
}) {
  const slides = payload.slides || [];
  const count = slides.length;
  // View state is keyed by the rendered bytes' identity — a new revision
  // or external edit gets fresh position/zoom; same bytes restores them.
  const viewKey = viewStateKey(payload);
  const [selected, setSelected] = useState(() => readView(viewKey, "slide", 0));
  const [zoom, setZoom] = useState(() => readView(viewKey, "zoom", 1));
  // Clamp at render — a source swap can leave `selected` past the end.
  const current = Math.min(selected, Math.max(0, count - 1));
  const slide = slides[current];
  // Re-key on source-identity change must run before the writers below —
  // otherwise a stale index/zoom lands under the new key first.
  useEffect(() => {
    setSelected(readView(viewKey, "slide", 0));
    setZoom(readView(viewKey, "zoom", 1));
  }, [viewKey]);
  useEffect(() => {
    onFocus?.(count > 0 ? `slide ${current + 1} of ${count}` : null);
    writeView(viewKey, "slide", current);
  }, [current, count, onFocus, viewKey]);
  useEffect(() => {
    writeView(viewKey, "zoom", zoom);
  }, [viewKey, zoom]);
  // ←/→ step through slides — never while typing in a field.
  useEffect(() => {
    if (count < 2) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const t = e.target;
      if (t instanceof HTMLElement && t.closest("input, textarea, select, [contenteditable='true']")) return;
      e.preventDefault();
      setSelected((s) => {
        const cur = Math.min(s, count - 1);
        return Math.min(count - 1, Math.max(0, cur + (e.key === "ArrowRight" ? 1 : -1)));
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [count]);
  // Frame the wireframe at the deck's real aspect — a 4:3 file reads
  // visibly different from a 16:9 one; overflow scrolls inside the frame.
  const aspect =
    payload.slide_width && payload.slide_height
      ? `${payload.slide_width} / ${payload.slide_height}`
      : undefined;
  return (
    <div>
      <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
        {slides.map((s, i) => (
          <button
            key={i}
            onClick={() => setSelected(i)}
            className="shrink-0 rounded-[4px] border px-2 py-1 text-[11px] transition-colors"
            style={{
              borderColor: i === current ? "var(--accent)" : "var(--border)",
              background: i === current ? "var(--surface)" : "transparent",
              color: i === current ? "var(--ink)" : "var(--ink-2)",
              cursor: "pointer",
            }}
          >
            {i + 1}. {s.title || "Slide"}
          </button>
        ))}
      </div>
      {count > 0 && (
        <div className="mb-2 flex items-center justify-between gap-2 text-[11px] text-[var(--ink-3)]">
          {count > 1 ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelected((s) => Math.max(0, Math.min(s, count - 1) - 1))}
                disabled={current <= 0}
                className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
                aria-label="Previous slide"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="font-mono">
                {current + 1} / {count}
              </span>
              <button
                onClick={() => setSelected((s) => Math.min(count - 1, Math.min(s, count - 1) + 1))}
                disabled={current >= count - 1}
                className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
                aria-label="Next slide"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))}
              disabled={zoom <= 0.5}
              className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
              aria-label="Zoom out"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <span className="w-9 text-center font-mono">{Math.round(zoom * 100)}%</span>
            <button
              onClick={() => setZoom((z) => Math.min(2, Math.round((z + 0.25) * 100) / 100))}
              disabled={zoom >= 2}
              className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
              aria-label="Zoom in"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setZoom(1)}
              disabled={zoom === 1}
              className="rounded-[4px] border border-[var(--border)] px-1.5 py-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
            >
              Fit
            </button>
          </div>
        </div>
      )}
      {slide && (
        <div style={{ zoom } as CSSProperties}>
          <div
            className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)]/40 p-3"
            style={aspect ? { aspectRatio: aspect, overflowY: "auto" } : undefined}
          >
            {slide.title && (
              <div className="mb-2 text-[15px] font-semibold text-[var(--ink)]">{slide.title}</div>
            )}
            <ElementsView elements={slide.elements} />
          </div>
        </div>
      )}
    </div>
  );
}

function WorkbookView({
  payload,
  onFocus,
}: {
  payload: PreviewPayload;
  onFocus?: (label: string | null) => void;
}) {
  const sheets = payload.sheets || [];
  const [selected, setSelected] = useState(0);
  const current = Math.min(selected, Math.max(0, sheets.length - 1));
  const sheet = sheets[current];
  useEffect(() => {
    onFocus?.(sheet ? `sheet "${sheet.name}"` : null);
  }, [sheet, onFocus]);
  return (
    <div>
      <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
        {sheets.map((s, i) => (
          <button
            key={i}
            onClick={() => setSelected(i)}
            className="shrink-0 rounded-[4px] border px-2 py-1 text-[11px] transition-colors"
            style={{
              borderColor: i === current ? "var(--accent)" : "var(--border)",
              background: i === current ? "var(--surface)" : "transparent",
              color: i === current ? "var(--ink)" : "var(--ink-2)",
              cursor: "pointer",
            }}
          >
            {s.name}
          </button>
        ))}
      </div>
      {sheet && (
        <>
          <GridTable header={[]} rows={sheet.rows} />
          {sheet.truncated && <TruncatedFlag />}
        </>
      )}
      {payload.formulas_recalculated === false && (
        <p className="mt-2 text-[11px] text-[var(--ink-3)]">
          Formulas shown as written — not recalculated.
        </p>
      )}
    </div>
  );
}

/** Isolated deck player — sandboxed iframe (allow-scripts, NO
 *  allow-same-origin) over the admitted /workspace/deck endpoint. Platform
 *  chrome lives outside the frame; the deck runtime reports state and
 *  accepts index-only nav messages through a schema-checked bridge. */
function DeckView({
  payload,
  backend,
  source,
  onFocus,
}: {
  payload: PreviewPayload;
  backend: PreviewBackend;
  source: PreviewSource;
  onFocus?: (label: string | null) => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fs, setFs] = useState(false);
  const [pos, setPos] = useState<{
    index: number;
    count: number;
    canPrev: boolean;
    canNext: boolean;
    pending: number;
  } | null>(null);
  const srcKey = `${source.path ?? ""}|${source.artifactId ?? ""}|${source.revisionId ?? ""}|${source.sessionId ?? ""}`;

  useEffect(() => {
    if (!backend.deckUrl) {
      setError("Deck playback isn't available on this surface — download the file to view it.");
      return;
    }
    let live = true;
    setUrl(null);
    setError(null);
    setPos(null);
    backend
      .deckUrl(source)
      .then((u) => live && setUrl(u))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend, srcKey]);

  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      const f = frameRef.current;
      if (!f || e.source !== f.contentWindow) return;
      const d = e.data as Record<string, unknown> | null;
      if (
        d &&
        d.caberos === "deck" &&
        d.v === 1 &&
        d.type === "state" &&
        Number.isInteger(d.index) &&
        Number.isInteger(d.count)
      ) {
        const idx = d.index as number;
        const cnt = d.count as number;
        const next = {
          index: idx,
          count: cnt,
          // rt2 reports canPrev/canNext (reveal-aware); rt1 doesn't — derive.
          canPrev: typeof d.canPrev === "boolean" ? d.canPrev : idx > 0,
          canNext: typeof d.canNext === "boolean" ? d.canNext : idx < cnt - 1,
          pending: Number.isInteger(d.pending) ? (d.pending as number) : 0,
        };
        setPos(next);
        onFocus?.(`slide ${next.index + 1} of ${next.count}`);
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [onFocus]);

  // Fullscreen covers the whole player (chrome included) so an exit
  // affordance stays reachable — iframe-only fullscreen leaves no way out
  // but the Escape key.
  useEffect(() => {
    const onFs = () => setFs(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // rt2: step (not absolute nav) — the runtime reveals pending build steps
  // before changing slides, and reports canPrev/canNext through state.
  // rt1: only understands absolute nav — send clamped index jumps instead.
  const step = (dir: 1 | -1) => {
    const rt1 = payload.deck?.runtime === "deck-rt1";
    const msg = rt1
      ? {
          caberos: "deck",
          v: 1,
          type: "nav",
          index: Math.max(0, Math.min((pos?.count ?? 1) - 1, (pos?.index ?? 0) + dir)),
        }
      : { caberos: "deck", v: 1, type: "step", dir };
    frameRef.current?.contentWindow?.postMessage(msg, "*");
  };

  if (error) return <Note text={error} />;
  if (!url) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />
      </div>
    );
  }
  const count = pos?.count ?? payload.deck?.slides ?? 0;
  const index = pos?.index ?? 0;
  return (
    <div
      ref={wrapRef}
      className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]"
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") step(1);
        else if (e.key === "ArrowLeft") step(-1);
      }}
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] px-2 py-1">
        <span className="text-[11px] tabular-nums text-[var(--ink-3)]">
          {count ? `${index + 1} / ${count}` : "…"}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous slide"
            disabled={pos ? !pos.canPrev : !count}
            onClick={() => step(-1)}
            className="rounded p-1 text-[var(--ink-2)] hover:bg-[var(--surface-2)] disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Next slide"
            disabled={pos ? !pos.canNext : !count}
            onClick={() => step(1)}
            className="rounded p-1 text-[var(--ink-2)] hover:bg-[var(--surface-2)] disabled:opacity-40"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label={fs ? "Exit fullscreen" : "Fullscreen"}
            onClick={() =>
              fs
                ? document.exitFullscreen()
                : wrapRef.current?.requestFullscreen?.()
            }
            className="rounded p-1 text-[var(--ink-2)] hover:bg-[var(--surface-2)]"
          >
            {fs ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
      <iframe
        ref={frameRef}
        src={url}
        title={payload.deck?.title || payload.name}
        // allow-scripts ONLY — no allow-same-origin: deck JS runs on an
        // opaque origin with no access to app cookies/storage/DOM.
        sandbox="allow-scripts"
        allowFullScreen
        className="min-h-0 w-full flex-1 border-0 bg-white"
      />
    </div>
  );
}

function MediaView({
  backend,
  source,
  media,
  expanded,
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  media: "audio" | "video";
  expanded?: boolean;
}) {
  const { url, loading, error } = useObjectUrl(
    () => backend.blob(source),
    [backend, source.path, source.artifactId, source.revisionId],
  );
  if (error) return <Note text={error} />;
  if (loading || !url) return <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />;
  return media === "video" ? (
    <video
      src={url}
      controls
      className={`${expanded ? "max-h-[80vh]" : "max-h-[70vh]"} max-w-full rounded-[5px]`}
    />
  ) : (
    <audio src={url} controls className={expanded ? "w-[560px] max-w-full" : "w-full"} />
  );
}

function UnknownView({ payload }: { payload: PreviewPayload }) {
  return (
    <div className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)] p-4 text-[12px] text-[var(--ink-2)]">
      <p className="mb-1 font-medium text-[var(--ink)]">{payload.name}</p>
      <p>{payload.mime || "unknown type"}</p>
      <p>{formatBytes(payload.size)}</p>
      {payload.too_large && <p className="mt-1 italic">Too large to preview.</p>}
      <p className="mt-2 text-[var(--ink-3)]">No preview available — download to inspect.</p>
    </div>
  );
}
