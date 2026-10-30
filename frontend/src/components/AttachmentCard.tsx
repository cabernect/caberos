import { ChevronLeft, ChevronRight, Link as LinkIcon, X } from "lucide-react";

import { attachmentKind, formatAttachmentSize } from "../lib/attachmentUtils";
import { FileTypeTile } from "./FileTypeTile";

/** One attachment card for both the composer tray (draft mode — reorder/
 *  remove controls) and sent user messages (open mode — preview/new tab).
 *  The parent resolves the thumbnail: the composer passes an ephemeral
 *  object URL; the message card fetches stored bytes via the preview
 *  backend. */
export interface AttachmentCardProps {
  type: string; // "file" | "image" | "url" | "image_url"
  filename: string;
  mimeType?: string;
  size?: number;
  url?: string; // url attachments — link target + hostname meta
  title?: string; // display-name override (fetched URL title)
  thumbUrl?: string | null; // resolved thumbnail, null while loading
  onOpen?: () => void; // sent mode — open preview
  controls?: {
    onMoveLeft: () => void;
    onMoveRight: () => void;
    onRemove: () => void;
    canMoveLeft: boolean;
    canMoveRight: boolean;
  };
}

export function AttachmentCard({
  type,
  filename,
  mimeType,
  size,
  url,
  title,
  thumbUrl,
  onOpen,
  controls,
}: AttachmentCardProps) {
  const isUrl = type === "url" || type === "image_url";

  let hostname = "";
  if (url) {
    try {
      hostname = new URL(url).hostname;
    } catch {
      hostname = url;
    }
  }

  const ext = filename.includes(".") ? filename.split(".").pop()!.toUpperCase() : "";
  const meta = isUrl
    ? hostname || "link"
    : `${ext && ext.length <= 5 ? ext : attachmentKind(filename, mimeType ?? "")}${
        size != null ? ` · ${formatAttachmentSize(size)}` : ""
      }`;
  const name = isUrl ? title || hostname || url || "" : filename;

  const inner = (
    <>
      {thumbUrl ? (
        <img
          src={thumbUrl}
          alt={name}
          className="h-9 w-9 shrink-0 rounded-[4px] border border-[var(--border)] object-cover"
        />
      ) : isUrl ? (
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] border border-[var(--border)] bg-[var(--surface)] text-[var(--ink-3)]">
          <LinkIcon className="h-4 w-4" />
        </span>
      ) : (
        <FileTypeTile filename={filename} />
      )}
      <span className="min-w-0 flex-1">
        <span
          className="block max-w-[160px] truncate text-[12px] font-medium text-[var(--ink)]"
          title={isUrl ? url : filename}
        >
          {name}
        </span>
        <span className="block text-[10px] text-[var(--ink-3)]">{meta}</span>
      </span>
      {controls && (
        <span className="flex items-center">
          <button
            onClick={controls.onMoveLeft}
            disabled={!controls.canMoveLeft}
            aria-label={`Move ${filename || "attachment"} earlier`}
            className="rounded-[3px] p-0.5 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)] disabled:opacity-30"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <ChevronLeft className="h-3 w-3" />
          </button>
          <button
            onClick={controls.onMoveRight}
            disabled={!controls.canMoveRight}
            aria-label={`Move ${filename || "attachment"} later`}
            className="rounded-[3px] p-0.5 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--ink)] disabled:opacity-30"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <ChevronRight className="h-3 w-3" />
          </button>
          <button
            onClick={controls.onRemove}
            aria-label={`Remove ${filename || "attachment"}`}
            className="rounded-[3px] p-0.5 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--danger)]"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
    </>
  );

  const cardClass =
    "group flex items-center gap-2 rounded-md border px-2.5 py-2 text-left transition hover:opacity-80";
  const cardStyle: React.CSSProperties = {
    background: "var(--white)",
    borderColor: "var(--border)",
    textDecoration: "none",
  };

  // Draft-mode URL chips stay plain — a live <a> can't legally nest the
  // reorder/remove buttons.
  if (isUrl && url && !controls) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className={cardClass} style={cardStyle}>
        {inner}
      </a>
    );
  }
  if (onOpen) {
    return (
      <button
        onClick={onOpen}
        className={cardClass}
        style={{ ...cardStyle, cursor: "pointer" }}
        title={`Preview ${filename}`}
      >
        {inner}
      </button>
    );
  }
  return (
    <div className={cardClass} style={cardStyle} title={isUrl ? url : filename}>
      {inner}
    </div>
  );
}
