import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * W13 rule: lists use rows, not cards. A row is [leading] title + sub /
 * [trailing]. Clickable rows get cursor + hover; dividers come from
 * `divide-y divide-line` on the parent.
 */
export function ListRow({
  leading,
  title,
  sub,
  trailing,
  onClick,
  className,
}: {
  leading?: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  trailing?: ReactNode;
  onClick?: () => void;
  className?: string;
}) {
  const inner = (
    <>
      {leading && <div className="shrink-0">{leading}</div>}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium leading-5 text-ink">{title}</div>
        {sub && <div className="truncate text-[13px] leading-[18px] text-ink-muted">{sub}</div>}
      </div>
      {trailing && <div className="flex shrink-0 items-center gap-2">{trailing}</div>}
    </>
  );
  const classes = cn("flex items-center gap-3 px-4 py-3", className);
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(classes, "w-full cursor-pointer text-left transition-colors duration-150 hover:bg-sunken")}
      >
        {inner}
      </button>
    );
  }
  return <div className={classes}>{inner}</div>;
}
