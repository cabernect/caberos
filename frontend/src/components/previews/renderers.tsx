import { useState } from "react";
import { ChevronLeft, ChevronRight, FileWarning, Loader2 } from "lucide-react";
import type { PreviewBackend, PreviewSource } from "@/lib/api";
import type { PreviewElement, PreviewPayload } from "@/lib/types";
import { Markdown } from "@/components/Markdown";
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
}: {
  payload: PreviewPayload;
  backend: PreviewBackend;
  source: PreviewSource;
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
        <GridTable header={payload.header || []} rows={payload.rows || []} />
      );
    case "image":
      return <ImageView backend={backend} source={source} name={payload.name} />;
    case "pdf":
      return <PdfView backend={backend} source={source} pageCount={payload.page_count || 0} />;
    case "document":
      return <ElementsView elements={payload.elements || []} />;
    case "slides":
      return <SlidesView payload={payload} />;
    case "workbook":
      return <WorkbookView payload={payload} />;
    case "media":
      return (
        <MediaView backend={backend} source={source} media={payload.media || "audio"} />
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
        <div className="prose-sm max-w-none text-[13px] text-[var(--ink)]">
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
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  name: string;
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
      className="max-h-[70vh] max-w-full rounded-[5px] border border-[var(--border)] object-contain"
    />
  );
}

function PdfView({
  backend,
  source,
  pageCount,
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  pageCount: number;
}) {
  const [page, setPage] = useState(1);
  const { url, loading, error } = useObjectUrl(
    () => backend.pdfPage(page, source),
    [backend, page, source.path, source.artifactId, source.revisionId],
  );
  if (pageCount === 0) return <Note text="No pages to render." />;
  return (
    <div>
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
          className="max-h-[70vh] max-w-full rounded-[5px] border border-[var(--border)]"
        />
      )}
    </div>
  );
}

/** The shared W2 element vocabulary — one renderer for docx + slide content. */
export function ElementsView({ elements }: { elements: PreviewElement[] }) {
  return (
    <div className="space-y-2 text-[13px] text-[var(--ink)]">
      {elements.map((el, i) => {
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
      })}
      {elements.length === 0 && <p className="text-[var(--ink-3)]">Empty document.</p>}
    </div>
  );
}

function SlidesView({ payload }: { payload: PreviewPayload }) {
  const slides = payload.slides || [];
  const [selected, setSelected] = useState(0);
  const slide = slides[selected];
  return (
    <div>
      <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
        {slides.map((s, i) => (
          <button
            key={i}
            onClick={() => setSelected(i)}
            className="shrink-0 rounded-[4px] border px-2 py-1 text-[11px] transition-colors"
            style={{
              borderColor: i === selected ? "var(--accent)" : "var(--border)",
              background: i === selected ? "var(--surface)" : "transparent",
              color: i === selected ? "var(--ink)" : "var(--ink-2)",
              cursor: "pointer",
            }}
          >
            {i + 1}. {s.title || "Slide"}
          </button>
        ))}
      </div>
      {slide && (
        <div className="rounded-[5px] border border-[var(--border)] bg-[var(--surface)]/40 p-3">
          {slide.title && (
            <div className="mb-2 text-[15px] font-semibold text-[var(--ink)]">{slide.title}</div>
          )}
          <ElementsView elements={slide.elements} />
        </div>
      )}
    </div>
  );
}

function WorkbookView({ payload }: { payload: PreviewPayload }) {
  const sheets = payload.sheets || [];
  const [selected, setSelected] = useState(0);
  const sheet = sheets[selected];
  return (
    <div>
      <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
        {sheets.map((s, i) => (
          <button
            key={i}
            onClick={() => setSelected(i)}
            className="shrink-0 rounded-[4px] border px-2 py-1 text-[11px] transition-colors"
            style={{
              borderColor: i === selected ? "var(--accent)" : "var(--border)",
              background: i === selected ? "var(--surface)" : "transparent",
              color: i === selected ? "var(--ink)" : "var(--ink-2)",
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

function MediaView({
  backend,
  source,
  media,
}: {
  backend: PreviewBackend;
  source: PreviewSource;
  media: "audio" | "video";
}) {
  const { url, loading, error } = useObjectUrl(
    () => backend.blob(source),
    [backend, source.path, source.artifactId, source.revisionId],
  );
  if (error) return <Note text={error} />;
  if (loading || !url) return <Loader2 className="h-5 w-5 animate-spin text-[var(--ink-3)]" />;
  return media === "video" ? (
    <video src={url} controls className="max-h-[70vh] max-w-full rounded-[5px]" />
  ) : (
    <audio src={url} controls className="w-full" />
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
