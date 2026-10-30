import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * W13 rule: empty states explain what to do next. Icon + title + guidance
 * copy + optional action button.
 */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-md border border-dashed border-line px-6 py-12 text-center",
        className
      )}
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-md bg-sunken">
        <Icon className="h-5 w-5 text-ink-faint" />
      </div>
      <div className="mt-3 text-[14px] font-semibold leading-5 text-ink">{title}</div>
      <div className="mt-1 max-w-sm text-[13px] leading-[18px] text-ink-muted">{children}</div>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
