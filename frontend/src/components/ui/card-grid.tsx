import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Responsive auto-fill grid for openable/editable cards (no card-in-card). */
export function CardGrid({
  children,
  minWidth = 260,
  className,
}: {
  children: ReactNode;
  minWidth?: number;
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-4", className)}
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))` }}
    >
      {children}
    </div>
  );
}
