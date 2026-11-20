import { Info } from "lucide-react";
import type { PreviewPayload } from "@/lib/types";

const messages: Partial<Record<PreviewPayload["kind"], string>> = {
  slides:
    "Extracted slide content, not the PowerPoint layout. Design and animations are not rendered; some elements may be omitted.",
  document:
    "Page layout, fonts, fields, and some content may differ from Word or be omitted.",
  workbook:
    "Some formatting and workbook features are not shown. Formulas are not calculated here.",
};

export function OfficePreviewNotice({
  kind,
  mode,
}: {
  kind: PreviewPayload["kind"];
  mode?: PreviewPayload["mode"];
}) {
  const message = mode === "approximate" ? messages[kind] : undefined;
  if (!message) return null;

  return (
    <div
      role="note"
      aria-label="Office preview limitations"
      className="flex shrink-0 items-start gap-2 border-b border-line bg-surface px-3 py-2 text-xs leading-relaxed text-ink-muted"
    >
      <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
      <p className="min-w-0">
        <span className="font-medium text-ink">Limited preview. </span>
        {message}
      </p>
    </div>
  );
}
