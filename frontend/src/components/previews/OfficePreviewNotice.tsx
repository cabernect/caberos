import { Info } from "lucide-react";
import type { PreviewPayload } from "@/lib/types";

const messages: Partial<Record<PreviewPayload["kind"], string>> = {
  slides:
    "Layout, fonts, animations, and some elements may differ from PowerPoint or be omitted.",
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
      className="flex shrink-0 items-start gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[12px] leading-relaxed text-[var(--ink-2)]"
    >
      <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
      <p className="min-w-0">
        <span className="font-medium text-[var(--ink)]">Limited preview. </span>
        {message}
      </p>
    </div>
  );
}
