import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** W13 stat card: caption label → 24/30 semibold value → optional sublabel. */
export function StatCard({
  label,
  value,
  sublabel,
  className,
}: {
  label: string;
  value: ReactNode;
  sublabel?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border border-line bg-surface px-4 py-3", className)}>
      <div className="text-[12px] leading-4 text-ink-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold leading-[30px] text-ink">{value}</div>
      {sublabel && <div className="mt-0.5 text-[12px] leading-4 text-ink-faint">{sublabel}</div>}
    </div>
  );
}
