import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal, flushSync } from "react-dom";
import { ChevronLeft, ChevronRight, FileWarning, Loader2, Presentation, X, ZoomIn, ZoomOut } from "lucide-react";
import type { PreviewBackend, PreviewSource } from "@/lib/api";
import type { DeckBlock, DeckEffect, DeckSlide, DeckSpec, PreviewElement, PreviewPayload } from "@/lib/types";
import { Markdown } from "@/components/Markdown";
import { readView, viewStateKey, writeView } from "./viewState";
import { useObjectUrl } from "./useObjectUrl";
import { DeckChart } from "./DeckChart";
import { DeckMotion } from "./deckMotion";
import { revealSteps, useReducedMotion } from "./deckPlayback";

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
    case "html":
      return <HtmlView key={source.revisionId || source.path} payload={payload} />;
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
      return <DeckView payload={payload} source={source} onFocus={onFocus} />;
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

/** Shared Rendered/Source-style toggle — every kind that offers a source
 *  view uses this so the control looks and behaves identically. */
function ModeToggle({
  value,
  options,
  disabledOptions,
  onChange,
}: {
  value: string;
  options: readonly string[];
  disabledOptions?: readonly string[];
  onChange: (mode: string) => void;
}) {
  return (
    <div className="flex shrink-0 gap-1 text-[11px]">
      {options.map((m) => {
        const active = m === value;
        const disabled = disabledOptions?.includes(m) ?? false;
        return (
          <button
            key={m}
            onClick={() => onChange(m)}
            aria-pressed={active}
            disabled={disabled}
            className="rounded-[4px] border px-2 py-1 transition-colors disabled:opacity-40"
            style={{
              borderColor: "var(--border)",
              background: active ? "var(--accent)" : "var(--surface)",
              color: active ? "var(--white)" : "var(--ink-2)",
              cursor: "pointer",
            }}
          >
            {m}
          </button>
        );
      })}
    </div>
  );
}

function MarkdownView({ content, truncated }: { content: string; truncated?: boolean }) {
  const [mode, setMode] = useState("Rendered");
  return (
    <div>
      <div className="mb-2">
        <ModeToggle
          value={mode}
          options={["Rendered", "Source"]}
          onChange={setMode}
        />
      </div>
      {mode === "Source" ? (
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

function HtmlView({ payload }: { payload: PreviewPayload }) {
  const [mode, setMode] = useState("Rendered");
  const rendered = mode === "Rendered" && !!payload.html_document;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 pb-2">
        <ModeToggle
          value={rendered ? "Rendered" : "Source"}
          options={["Rendered", "Source"]}
          disabledOptions={payload.html_document ? undefined : ["Rendered"]}
          onChange={setMode}
        />
      </div>
      <p className="shrink-0 pb-2 text-[11px] text-[var(--ink-3)]">
        Static HTML preview. Scripts, links, forms, and external/local asset loading are disabled.
      </p>
      {rendered ? (
        <iframe
          title={`HTML preview: ${payload.name}`}
          srcDoc={payload.html_document!}
          sandbox=""
          referrerPolicy="no-referrer"
          className="min-h-0 w-full flex-1 border-0 bg-white"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          <TextView content={payload.content || ""} language="html" truncated={payload.truncated} />
        </div>
      )}
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
  const content = slide?.elements.filter((el) => el.type !== "notes") ?? [];
  const notes = slide?.elements.filter((el) => el.type === "notes") ?? [];
  const aspectRatio =
    payload.slide_width && payload.slide_width > 0 &&
    payload.slide_height && payload.slide_height > 0
      ? `${payload.slide_width} / ${payload.slide_height}`
      : "16 / 9";
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
  return (
    <div className="min-w-0">
      {count > 0 && (
        <select
          aria-label="Go to slide"
          value={current}
          onChange={(e) => setSelected(Number(e.target.value))}
          className="mb-2 h-8 w-full min-w-0 truncate rounded-[4px] border border-[var(--border)] bg-[var(--surface)] px-2 text-[12px] text-[var(--ink)] focus-visible:outline focus-visible:outline-[var(--accent)]"
        >
          {slides.map((s, i) => (
            <option key={i} value={i}>
              {i + 1}. {s.title || "Untitled slide"}
            </option>
          ))}
        </select>
      )}
      {count > 0 && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--ink-3)]">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelected((s) => Math.max(0, Math.min(s, count - 1) - 1))}
              disabled={current <= 0}
              className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
              aria-label="Previous slide"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span aria-live="polite" className="font-mono tabular-nums">
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
        <>
          <section
            aria-label={`Slide ${current + 1} content`}
            className="relative w-full overflow-hidden rounded-[5px] border border-[var(--border)] bg-[var(--white)]"
            style={{ aspectRatio }}
          >
            {/* Keep content and zoom from changing the slide frame's size. */}
            <div
              key={`${viewKey}:${current}`}
              tabIndex={0}
              aria-label="Scrollable slide content"
              className="absolute inset-0 overflow-auto focus-visible:outline focus-visible:outline-[var(--accent)] focus-visible:-outline-offset-2"
            >
              <div className="p-5 sm:p-6" style={{ zoom } as CSSProperties}>
                <p className="mb-3 text-[10px] font-medium uppercase tracking-widest text-[var(--ink-3)]">
                  Slide {current + 1} · Extracted content
                </p>
                <h2 className="mb-4 break-words text-[20px] font-semibold leading-snug text-[var(--ink)]">
                  {slide.title || "Untitled slide"}
                </h2>
                {content.length ? (
                  <div className="break-words leading-relaxed">
                    <ElementsView elements={content} />
                  </div>
                ) : (
                  <p className="text-[12px] text-[var(--ink-3)]">No extractable body content on this slide.</p>
                )}
              </div>
            </div>
          </section>
          {notes.length > 0 && (
            <details
              key={`${viewKey}:${current}`}
              className="mt-3 rounded-[5px] border border-[var(--border)] text-[12px] text-[var(--ink-2)]"
            >
              <summary className="cursor-pointer rounded-[5px] px-3 py-2 font-medium hover:bg-[var(--surface)]">
                Speaker notes
              </summary>
              <div className="space-y-2 border-t border-[var(--border)] px-3 py-3">
                {notes.map((note, i) => (
                  <p key={i} className="whitespace-pre-wrap break-words leading-relaxed">{note.text}</p>
                ))}
              </div>
            </details>
          )}
        </>
      )}
      {!count && <Note text="No slides to preview." />}
    </div>
  );
}

function colLetter(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

/** "B2" → {col:1,row:1} (0-based); null on junk. */
function parseCellRef(ref: string): { col: number; row: number } | null {
  const m = /^([A-Za-z]{1,3})([0-9]+)$/.exec(ref.trim());
  if (!m) return null;
  let col = 0;
  for (const ch of m[1].toUpperCase()) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { col: col - 1, row: parseInt(m[2], 10) - 1 };
}

/** "A1:C3" → bounds; single "B2" → 1x1. */
function parseRange(ref: string): { c0: number; r0: number; c1: number; r1: number } | null {
  const parts = ref.split(":");
  const a = parseCellRef(parts[0]);
  if (!a) return null;
  const b = parts[1] ? parseCellRef(parts[1]) : a;
  if (!b) return null;
  return {
    c0: Math.min(a.col, b.col),
    r0: Math.min(a.row, b.row),
    c1: Math.max(a.col, b.col),
    r1: Math.max(a.row, b.row),
  };
}

/** Common Excel number formats → display string. Unknown formats show the
 *  raw value; the format itself is preview metadata, not a claim of Excel
 *  rendering. */
function formatCellValue(v: unknown, numFmt?: string): string {
  if (v == null) return "";
  if (typeof v === "number" && numFmt) {
    if (numFmt.includes("%")) {
      const dec = /0\.(0+)/.exec(numFmt)?.[1].length ?? 0;
      return `${(v * 100).toFixed(dec)}%`;
    }
    if (numFmt.includes(",")) {
      const dec = /0\.(0+)/.exec(numFmt)?.[1].length ?? 0;
      return v.toLocaleString(undefined, {
        minimumFractionDigits: dec,
        maximumFractionDigits: dec,
      });
    }
  }
  return String(v);
}

function WorkbookGrid({ sheet }: { sheet: NonNullable<PreviewPayload["sheets"]>[number] }) {
  const [sel, setSel] = useState<{ r: number; c: number } | null>(null);
  const grid = sheet.grid;
  if (!grid) {
    // Legacy payload shape — plain value rows.
    const rows = sheet.rows || [];
    return (
      <div className="overflow-auto rounded-[5px] border border-[var(--border)]">
        <table className="w-full border-collapse text-[12px]">
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className={i % 2 ? "bg-[var(--surface)]/50" : ""}>
                {(row as unknown[]).map((cell, j) => (
                  <td key={j} className="border-b border-[var(--border)] px-2.5 py-1 text-[var(--ink)]">
                    {cell == null ? "" : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const rows = grid.length;
  const cols = grid.reduce((m, r) => Math.max(m, r.length), 0);

  // Merge map: anchor → span, covered → skip.
  const spans = new Map<string, { cs: number; rs: number }>();
  const covered = new Set<string>();
  for (const ref of sheet.merges || []) {
    const b = parseRange(ref);
    if (!b) continue;
    spans.set(`${b.r0}:${b.c0}`, {
      cs: b.c1 - b.c0 + 1,
      rs: b.r1 - b.r0 + 1,
    });
    for (let r = b.r0; r <= b.r1; r++)
      for (let c = b.c0; c <= b.c1; c++)
        if (r !== b.r0 || c !== b.c0) covered.add(`${r}:${c}`);
  }

  // Freeze panes: "B2" → row 0 sticky top, col 0 sticky left.
  const freeze = sheet.freeze ? parseCellRef(sheet.freeze) : null;
  const freezeRow = freeze ? freeze.row : Infinity;
  const freezeCol = freeze ? freeze.col : Infinity;

  // Column widths in px (Excel width ≈ chars; ~7px/char + padding).
  const colPx = (c: number) => {
    const w = sheet.col_widths?.[colLetter(c)];
    return w ? Math.round(w * 7 + 10) : undefined;
  };

  const stickyTop = (r: number) =>
    r < freezeRow
      ? { position: "sticky" as const, top: (r + 1) * 26, zIndex: 2 }
      : {};
  const stickyLeft = (c: number) => {
    if (c >= freezeCol) return {};
    let left = 40; // row-number gutter
    for (let i = 0; i < c; i++) left += colPx(i) ?? 88;
    return { position: "sticky" as const, left, zIndex: 3 };
  };

  const cellAt = (r: number, c: number) => grid[r]?.[c] ?? null;
  const selCell = sel ? cellAt(sel.r, sel.c) : null;
  const selRef = sel ? `${colLetter(sel.c)}${sel.r + 1}` : "";

  return (
    <div>
      {/* Formula bar — click a cell to inspect its raw content/formula. */}
      <div className="mb-1 flex items-center gap-2 rounded-[5px] border border-[var(--border)] bg-[var(--surface)] px-2 py-1">
        <span className="w-14 shrink-0 truncate text-[11px] font-medium text-[var(--ink-3)]">
          {selRef || "—"}
        </span>
        <span className="shrink-0 text-[11px] italic text-[var(--ink-3)]">fx</span>
        <span className="truncate text-[12px] text-[var(--ink)]">
          {selCell
            ? typeof selCell.v === "string" && selCell.v.startsWith("=")
              ? selCell.v
              : String(selCell.v ?? "")
            : sel
              ? "(empty)"
              : "Click a cell"}
        </span>
      </div>
      <div className="overflow-auto rounded-[5px] border border-[var(--border)]">
      <table
        className="border-collapse text-[12px]"
        style={{ tableLayout: "fixed" }}
      >
        <colgroup>
          <col style={{ width: 40 }} />
          {Array.from({ length: cols }, (_, c) => (
            <col key={c} style={{ width: colPx(c) ?? 96 }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th
              className="border-b border-r border-[var(--border)] bg-[var(--surface)] px-1 py-0.5 text-center text-[10px] font-medium text-[var(--ink-3)]"
              style={{ position: "sticky", top: 0, left: 0, zIndex: 4 }}
            />
            {Array.from({ length: cols }, (_, c) => (
              <th
                key={c}
                className="border-b border-[var(--border)] bg-[var(--surface)] px-1.5 py-0.5 text-center text-[10px] font-semibold uppercase tracking-wide text-[var(--ink-3)]"
                style={{
                  position: "sticky",
                  top: 0,
                  ...(c < freezeCol ? stickyLeft(c) : {}),
                  zIndex: 4,
                }}
              >
                {colLetter(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r} className="hover:bg-[var(--surface)]/60">
              <td
                className="border-b border-r border-[var(--border)] bg-[var(--surface)] px-1 py-0.5 text-center text-[10px] font-medium text-[var(--ink-3)]"
                style={{
                  position: "sticky",
                  left: 0,
                  ...(r < freezeRow ? { top: (r + 1) * 26 } : {}),
                  zIndex: r < freezeRow ? 3 : 1,
                }}
              >
                {r + 1}
              </td>
              {Array.from({ length: cols }, (_, c) => {
                const key = `${r}:${c}`;
                if (covered.has(key)) return null;
                const cell = cellAt(r, c);
                const span = spans.get(key);
                const st = cell?.s;
                const isNum = typeof cell?.v === "number";
                const isSel = sel?.r === r && sel?.c === c;
                const style: CSSProperties = {
                  borderRight: "1px solid var(--border)",
                  ...(st?.f ? { backgroundColor: st.f } : {}),
                  ...(st?.c ? { color: st.c } : {}),
                  ...(st?.b ? { fontWeight: 600 } : {}),
                  ...(st?.i ? { fontStyle: "italic" } : {}),
                  ...(st?.sz ? { fontSize: st.sz } : {}),
                  ...(isNum
                    ? { textAlign: "right", fontVariantNumeric: "tabular-nums" }
                    : st?.a && st.a !== "general"
                      ? { textAlign: st.a as CSSProperties["textAlign"] }
                      : {}),
                  ...(st?.w ? { whiteSpace: "normal" } : { whiteSpace: "nowrap" }),
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  cursor: "cell",
                  ...(isSel ? { outline: "2px solid var(--accent)", outlineOffset: -2 } : {}),
                  ...stickyTop(r),
                  ...stickyLeft(c),
                };
                return (
                  <td
                    key={c}
                    colSpan={span?.cs}
                    rowSpan={span?.rs}
                    className="border-b border-[var(--border)] px-1.5 py-0.5 align-middle text-[var(--ink)]"
                    style={style}
                    title={
                      typeof cell?.v === "string" && cell.v.startsWith("=")
                        ? `formula: ${cell.v}`
                        : st?.n
                    }
                    onClick={() => setSel({ r, c })}
                  >
                    {cell ? formatCellValue(cell.v, st?.n) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {/* Status bar */}
      <div className="mt-1 flex items-center justify-between rounded-[5px] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-[10px] text-[var(--ink-3)]">
        <span>
          {sheet.name} · {rows}×{cols}
          {sheet.row_count > rows || (sheet.col_count ?? 0) > cols
            ? ` (of ${sheet.row_count}×${sheet.col_count ?? "?"})`
            : ""}
        </span>
        <span>formulas not recalculated</span>
      </div>
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
  const feat = sheet?.features;
  const featBits = feat
    ? [
        feat.tables?.length ? `${feat.tables.length} table${feat.tables.length > 1 ? "s" : ""}` : null,
        feat.charts ? `${feat.charts} chart${feat.charts > 1 ? "s" : ""}` : null,
        feat.data_validations ? `${feat.data_validations} data validation${feat.data_validations > 1 ? "s" : ""}` : null,
        feat.conditional_formats ? `${feat.conditional_formats} conditional format${feat.conditional_formats > 1 ? "s" : ""}` : null,
      ].filter(Boolean)
    : [];
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
          {featBits.length > 0 && (
            <p className="mb-2 text-[11px] text-[var(--ink-3)]">
              Contains {featBits.join(", ")} — shown as cell data; objects are not rendered.
            </p>
          )}
          <WorkbookGrid sheet={sheet} />
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
/** Presentation spec renderer — .deck.json slides drawn directly in React
 *  at a fixed 1280×720 design size, scaled to fit. No iframe, no generated
 *  HTML: the same normalized spec feeds the native PPTX export, so what the
 *  operator sees and what downloads share one source of truth. */

const DECK_W = 1280;
const DECK_H = 720;
const DECK_FONTS: Record<string, string> = {
  sans: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  serif: 'Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, "SF Mono", Menlo, monospace',
};

function DeckBlockView({
  block,
  spec,
  color,
  visibleItems,
  effect,
}: {
  block: DeckBlock;
  spec: DeckSpec;
  color: string;
  visibleItems?: number;
  effect?: DeckEffect;
}) {
  const base = { color, fontFamily: "inherit" } as const;
  switch (block.type) {
    case "chart":
      return <DeckChart block={block} />;
    case "heading":
      return (
        <div style={{ ...base, fontSize: 26, fontWeight: 700, margin: "10px 0 4px" }}>
          {String(block.text ?? "")}
        </div>
      );
    case "paragraph":
      return (
        <div style={{ ...base, fontSize: 19, lineHeight: 1.5, margin: "8px 0", whiteSpace: "pre-wrap" }}>
          {String(block.text ?? "")}
        </div>
      );
    case "bullets":
      return (
        <ul style={{ ...base, fontSize: 19, lineHeight: 1.55, margin: "8px 0", paddingLeft: 34 }}>
          {(block.items ?? []).map((item, i) => (
            <li key={i} style={{ margin: "5px 0", visibility: i < (visibleItems ?? Infinity) ? undefined : "hidden" }}>
              <DeckMotion visible={i < (visibleItems ?? Infinity)} effect={effect}>
                {String(item)}
              </DeckMotion>
            </li>
          ))}
        </ul>
      );
    case "table": {
      const rows = (block.rows ?? []) as unknown[][];
      if (!rows.length) return null;
      const cols = Math.max(...rows.map((r) => r.length));
      return (
        <table
          style={{
            ...base,
            fontSize: 17,
            borderCollapse: "collapse",
            margin: "10px 0",
            width: "100%",
          }}
        >
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {Array.from({ length: cols }, (_, c) => (
                  <td
                    key={c}
                    style={{
                      border: "1px solid rgba(128,128,128,0.35)",
                      padding: "7px 10px",
                      background: r === 0 ? "var(--accent, #315c73)" : "transparent",
                      color: r === 0 ? "#fff" : color,
                      fontWeight: r === 0 ? 600 : 400,
                    }}
                  >
                    {String(row[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    case "image": {
      const src = String(block.src ?? "");
      const uri =
        src.startsWith("data:") ? src : spec.assets?.find((a) => a.path === src)?.data_uri;
      if (!uri) {
        return (
          <div
            style={{
              ...base,
              fontSize: 16,
              border: "1px dashed rgba(128,128,128,0.5)",
              borderRadius: 8,
              padding: 18,
              margin: "10px 0",
              textAlign: "center",
              opacity: 0.7,
            }}
          >
            {block.alt ? `${block.alt} — ` : ""}image unavailable in this preview
          </div>
        );
      }
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={uri}
          alt={String(block.alt ?? "")}
          style={{ maxWidth: "100%", maxHeight: 340, objectFit: "contain", margin: "10px 0", display: "block" }}
        />
      );
    }
    case "divider":
      return <hr style={{ border: "none", borderTop: `3px solid var(--accent, #315c73)`, width: 120, margin: "18px 0" }} />;
    default:
      return (
        <div style={{ ...base, fontSize: 17, fontStyle: "italic", opacity: 0.7, margin: "8px 0" }}>
          [{block.type}]
        </div>
      );
  }
}

export function DeckSlideCanvas({ slide, spec, revealed = Infinity, animate = false }: {
  slide: DeckSlide; spec: DeckSpec; revealed?: number; animate?: boolean;
}) {
  const theme = spec.theme ?? {};
  const background = theme.background ?? "#ffffff";
  const accent = theme.accent ?? "#3f6212";
  const color = theme.text ?? "#1c1917";
  const font = DECK_FONTS[theme.font ?? "sans"] ?? DECK_FONTS.sans;
  const layout = slide.layout ?? "content";
  const centered = layout === "title" || layout === "section";
  const blocks = slide.blocks ?? [];
  const cssVars = { "--accent": accent } as CSSProperties;
  const steps = revealSteps(slide);

  const blockList = (list: typeof blocks) => (
    <>
      {list.map((b) => {
        const step = steps.blocks[blocks.indexOf(b)];
        const itemwise = b.reveal === "items";
        const effect = animate ? b.animation ?? spec.motion?.entrance ?? (b.reveal ? { type: "fade" as const } : undefined) : undefined;
        return (
          <DeckMotion
            key={b.id ?? blocks.indexOf(b)}
            visible={itemwise || !step.count || revealed > step.start}
            effect={itemwise ? undefined : effect}
          >
            <div data-block={b.id}>
            <DeckBlockView
              block={b}
              spec={spec}
              color={color}
              visibleItems={itemwise ? Math.max(0, revealed - step.start) : undefined}
              effect={itemwise ? effect : undefined}
            />
            </div>
          </DeckMotion>
        );
      })}
    </>
  );

  return (
    <div
      className="relative overflow-hidden"
      style={{
        width: DECK_W,
        height: DECK_H,
        background,
        color,
        fontFamily: font,
        ...cssVars,
      }}
    >
      {centered ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            padding: "0 120px",
          }}
        >
          {slide.title && (
            <div style={{ fontSize: layout === "section" ? 52 : 44, fontWeight: 800, lineHeight: 1.15, marginBottom: 28 }}>
              {slide.title}
            </div>
          )}
          <div style={{ maxWidth: 900 }}>{blockList(blocks)}</div>
        </div>
      ) : layout === "two_content" ? (
        <>
          {slide.title && (
            <div style={{ position: "absolute", top: 36, left: 64, right: 64, fontSize: 34, fontWeight: 700 }}>
              {slide.title}
            </div>
          )}
          <div style={{ position: "absolute", top: slide.title ? 110 : 48, bottom: 48, left: 64, right: 64, display: "flex", gap: 48 }}>
            <div style={{ flex: 1, minWidth: 0 }}>{blockList(blocks.filter((b) => (b.column ?? 0) !== 1))}</div>
            <div style={{ flex: 1, minWidth: 0 }}>{blockList(blocks.filter((b) => b.column === 1))}</div>
          </div>
        </>
      ) : (
        <>
          {slide.title && (
            <>
              <div style={{ position: "absolute", top: 40, left: 64, right: 64, fontSize: 34, fontWeight: 700 }}>
                {slide.title}
              </div>
              <div style={{ position: "absolute", top: 108, left: 64, width: 90, height: 5, background: accent }} />
            </>
          )}
          <div
            style={{
              position: "absolute",
              top: slide.title ? 150 : 56,
              bottom: 48,
              left: 64,
              right: 64,
              overflow: "hidden",
            }}
          >
            {blockList(blocks)}
          </div>
        </>
      )}
      <div style={{ position: "absolute", bottom: 14, left: 64, fontSize: 12, opacity: 0.55 }}>
        {spec.title}
      </div>
    </div>
  );
}

function DeckStage({ slide, spec, presenting = false, revealed = Infinity, reduced = false, reverse = false, onAdvance }: {
  slide: DeckSlide;
  spec: DeckSpec;
  presenting?: boolean;
  revealed?: number;
  reduced?: boolean;
  reverse?: boolean;
  onAdvance?: () => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const fit = () => {
      if (el.clientWidth && el.clientHeight) {
        setScale(Math.min(el.clientWidth / DECK_W, el.clientHeight / DECK_H));
      }
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={stageRef}
      className={`relative flex min-h-0 flex-1 items-center justify-center overflow-hidden ${
        presenting ? "bg-black" : "rounded-[5px] border border-[var(--border)] bg-[var(--surface-2)]"
      }`}
    >
      <div style={{ width: DECK_W * scale, height: DECK_H * scale, flexShrink: 0 }}>
        <div style={{ width: DECK_W, height: DECK_H, transform: `scale(${scale})`, transformOrigin: "top left" }}>
          <DeckMotion
            key={slide.id}
            effect={presenting && !reduced ? slide.transition ?? spec.motion?.transition : undefined}
            reverse={reverse}
          >
            <DeckSlideCanvas slide={slide} spec={spec} revealed={revealed} animate={presenting && !reduced} />
          </DeckMotion>
        </div>
      </div>
      {onAdvance && (
        <button
          type="button"
          aria-label="Advance presentation"
          className="absolute inset-0 cursor-pointer focus-visible:outline focus-visible:outline-white"
          onClick={onAdvance}
        />
      )}
    </div>
  );
}

function DeckSlideshow({ spec, index: initialIndex, rootRef, onSelect, onExit }: {
  spec: DeckSpec;
  index: number;
  rootRef: RefObject<HTMLDivElement | null>;
  onSelect: (index: number) => void;
  onExit: () => void;
}) {
  const count = spec.slides.length;
  const [playback, setPlayback] = useState({ index: initialIndex, step: 0, reverse: false });
  const index = Math.min(playback.index, count - 1);
  const { step } = playback;
  const reduced = useReducedMotion();
  const total = reduced ? 0 : revealSteps(spec.slides[index]).total;
  const select = (next: number, completed = false) => {
    const destination = Math.max(0, Math.min(count - 1, next));
    setPlayback({
      index: destination,
      step: completed ? revealSteps(spec.slides[destination]).total : 0,
      reverse: destination < index,
    });
    onSelect(destination);
  };
  const next = () => {
    if (step < total) setPlayback((p) => ({ ...p, step: Math.min(total, p.step + 1) }));
    else if (index < count - 1) select(index + 1);
  };
  const previous = () => {
    if (!reduced && step > 0) setPlayback((p) => ({ ...p, step: Math.max(0, p.step - 1) }));
    else if (index > 0) select(index - 1, true);
  };

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const previousFocus = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.focus();
    let enteredFullscreen = false;
    const onFullscreen = () => {
      if (document.fullscreenElement === root) enteredFullscreen = true;
      else if (enteredFullscreen) onExit();
    };
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreen);
      if (document.fullscreenElement === root) void document.exitFullscreen().catch(() => {});
      document.body.style.overflow = overflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [onExit, rootRef]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onExit();
        return;
      }
      if (event.key === "Tab") {
        const buttons = rootRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
        if (!buttons?.length) return;
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === rootRef.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === rootRef.current)) {
          event.preventDefault();
          first.focus();
        }
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === " " && target instanceof HTMLElement && target.closest("button")) return;
      let action: () => void;
      if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(event.key)) action = next;
      else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(event.key)) action = previous;
      else if (event.key === "Home") action = () => select(0);
      else if (event.key === "End") action = () => select(count - 1, true);
      else return;
      event.preventDefault();
      event.stopPropagation();
      action();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const buttonClass = "rounded-[4px] border border-white/25 p-2 hover:bg-white/15 focus-visible:outline focus-visible:outline-white disabled:opacity-40";
  return createPortal(
    <div
      ref={rootRef}
      data-deck-slideshow=""
      role="dialog"
      aria-modal="true"
      aria-label="Presentation slideshow"
      tabIndex={-1}
      className="fixed inset-0 z-[100] flex h-full w-full flex-col bg-black text-white outline-none"
    >
      <DeckStage slide={spec.slides[index]} spec={spec} presenting revealed={reduced ? Infinity : step} reduced={reduced} reverse={playback.reverse} onAdvance={next} />
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 bg-neutral-950 px-3 py-2 text-[12px]">
        <span className="hidden min-w-0 flex-1 truncate sm:block">{spec.title}</span>
        <div className="flex items-center gap-3">
          <button className={buttonClass} aria-label="Previous slide" disabled={index === 0 && (reduced || step === 0)} onClick={previous}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span aria-live="polite" className="font-mono tabular-nums">{index + 1} / {count}</span>
          {total > 0 && <span className="text-white/60" aria-live="polite">Reveal {Math.min(step, total)} / {total}</span>}
          <button className={buttonClass} aria-label="Next slide" disabled={index === count - 1 && step >= total} onClick={next}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <span className="hidden flex-1 text-right text-white/60 md:block">Arrow keys to navigate · Esc to exit</span>
        <button className={`${buttonClass} flex items-center gap-1.5`} onClick={onExit}>
          <X className="h-4 w-4" /> Exit slideshow
        </button>
      </div>
    </div>,
    document.body,
  );
}

function DeckView({
  payload,
  source,
  onFocus,
}: {
  payload: PreviewPayload;
  source: PreviewSource;
  onFocus?: (label: string | null) => void;
}) {
  const spec = payload.spec;
  const slides = spec?.slides ?? [];
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState("Slides");
  const [presenting, setPresenting] = useState(false);
  const slideshowRef = useRef<HTMLDivElement>(null);
  const exitSlideshow = useCallback(() => setPresenting(false), []);
  const startSlideshow = () => {
    // Mount before requesting fullscreen so the request stays in the user gesture,
    // rather than an effect that StrictMode may replay.
    flushSync(() => setPresenting(true));
    const root = slideshowRef.current;
    root?.requestFullscreen?.().then(() => {
      if (!root.isConnected && document.fullscreenElement === root) {
        void document.exitFullscreen().catch(() => {});
      }
    }).catch(() => {});
  };
  const srcKey = `${source.path ?? ""}|${source.artifactId ?? ""}|${source.revisionId ?? ""}|${source.sessionId ?? ""}`;
  const clamped = Math.min(index, Math.max(0, slides.length - 1));

  useEffect(() => {
    setIndex(0);
    setMode("Slides");
    setPresenting(false);
  }, [srcKey]);

  useEffect(() => {
    onFocus?.(
      mode === "Slides" && slides.length ? `slide ${clamped + 1} of ${slides.length}` : null,
    );
  }, [clamped, slides.length, onFocus, mode]);

  if (!spec || !slides.length) {
    return <Note text="This deck spec couldn't be rendered — download the file to inspect it." />;
  }

  const step = (dir: 1 | -1) =>
    setIndex((i) => Math.max(0, Math.min(slides.length - 1, i + dir)));

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      onKeyDown={(e) => {
        if (mode !== "Slides" || presenting) return;
        if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
      }}
    >
      <div className="flex items-center justify-between gap-2 px-1 pb-2">
        <ModeToggle
          value={mode}
          options={["Slides", "Source"]}
          onChange={setMode}
        />
        {mode === "Slides" && (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--ink-3)]">
            <button
              type="button"
              onClick={startSlideshow}
              className="flex items-center gap-1 rounded-[4px] border border-[var(--border)] px-2 py-1 text-[var(--ink-2)] transition-colors hover:bg-[var(--surface)]"
            >
              <Presentation className="h-3.5 w-3.5" /> Slideshow
            </button>
            <span className="font-mono tabular-nums">
              {slides.length ? `${clamped + 1} / ${slides.length}` : "…"}
            </span>
            <button
              type="button"
              aria-label="Previous slide"
              disabled={clamped <= 0}
              onClick={() => step(-1)}
              className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label="Next slide"
              disabled={clamped >= slides.length - 1}
              onClick={() => step(1)}
              className="rounded-[4px] border border-[var(--border)] p-1 transition-colors hover:bg-[var(--surface)] disabled:opacity-40"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
      {mode === "Source" ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <TextView content={payload.content || ""} language="json" truncated={payload.truncated} />
        </div>
      ) : (
        <DeckStage slide={slides[clamped]} spec={spec} />
      )}
      {presenting && (
        <DeckSlideshow spec={spec} index={clamped} rootRef={slideshowRef} onSelect={setIndex} onExit={exitSlideshow} />
      )}
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
