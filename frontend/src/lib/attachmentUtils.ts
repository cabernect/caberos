/** Composer attachment helpers (W3c) — pure functions so vitest can cover
 *  the dedupe/reorder/classify logic without mounting the composer. */

/** SHA-256 of file bytes → hex. Drives duplicate detection — identical
 *  bytes pasted or dropped twice collapse to one card. FileReader is used
 *  over file.arrayBuffer() for broader environment support (jsdom, older
 *  webviews). */
export async function fileHash(file: File): Promise<string> {
  const buf = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Display kind for the attachment card badge — mirrors the backend
 *  preview classifier (same extension sets, client-side cheap version). */
export function attachmentKind(filename: string, mimeType: string): string {
  const ext = filename.includes(".")
    ? filename.slice(filename.lastIndexOf(".")).toLowerCase()
    : "";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.startsWith("video/")) return "video";
  switch (ext) {
    case ".md":
    case ".markdown":
    case ".mdx":
      return "markdown";
    case ".pdf":
      return "pdf";
    case ".docx":
    case ".doc":
      return "document";
    case ".pptx":
    case ".ppt":
      return "slides";
    case ".xlsx":
    case ".xls":
      return "workbook";
    case ".csv":
    case ".tsv":
      return "table";
    case ".json":
      return "json";
    default:
      return mimeType.startsWith("text/") ? "text" : "file";
  }
}

/** Move an item within a list — shared by attachments + their parallel
 *  context-chip array so the two never drift out of alignment. */
export function moveItem<T>(list: T[], from: number, delta: number): T[] {
  const to = from + delta;
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
