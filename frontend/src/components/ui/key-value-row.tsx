import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Label / value row for settings and detail bodies. `mono` for IDs, code, model names. */
export function KeyValueRow({
  label,
  children,
  mono,
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 py-2", className)}>
      <div className="shrink-0 text-[13px] leading-[18px] text-ink-muted">{label}</div>
      <div className={cn("min-w-0 text-right text-[14px] leading-5 text-ink", mono && "font-mono text-[13px]")}>
        {children}
      </div>
    </div>
  );
}
