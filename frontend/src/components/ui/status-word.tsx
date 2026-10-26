import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusKind = "running" | "idle" | "paused" | "needs_setup" | "failed" | "success";

/**
 * W13 hard rule: status is a shape + a word + a color — never color alone.
 * The dot is the shape, the label is the word, the token supplies the color.
 */
const STATUS: Record<StatusKind, { label: string; dot: string; text: string; pulse?: boolean }> = {
  running: { label: "Running", dot: "bg-success", text: "text-success", pulse: true },
  idle: { label: "Idle", dot: "bg-ink-faint", text: "text-ink-muted" },
  paused: { label: "Paused", dot: "bg-warning", text: "text-warning" },
  needs_setup: { label: "Needs setup", dot: "bg-warning", text: "text-warning" },
  failed: { label: "Failed", dot: "bg-danger", text: "text-danger" },
  success: { label: "Done", dot: "bg-success", text: "text-success" },
};

export function StatusWord({
  status,
  label,
  className,
}: {
  status: StatusKind;
  /** Override the default word (e.g. "Idle · last run 2h ago"). */
  label?: ReactNode;
  className?: string;
}) {
  const s = STATUS[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[13px] leading-[18px]", s.text, className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot, s.pulse && "pulse")} />
      <span>{label ?? s.label}</span>
    </span>
  );
}
