import { cn } from "@/lib/utils";

export interface FilterPill {
  key: string;
  label: string;
  count?: number;
}

/**
 * W13 filter row: pill buttons under the page header. Active pill is the
 * ink fill (light in dark mode); inactive are bordered surface chips.
 */
export function FilterPills({
  pills,
  active,
  onChange,
  variant = "pills",
  className,
}: {
  pills: FilterPill[];
  active: string;
  onChange: (key: string) => void;
  /** "segmented" renders the connected-track control from the Agents mockup. */
  variant?: "pills" | "segmented";
  className?: string;
}) {
  if (variant === "segmented") {
    return (
      <div className={cn("inline-flex h-[34px] items-center gap-0.5 rounded-full bg-track p-1", className)}>
        {pills.map((pill) => {
          const isActive = pill.key === active;
          return (
            <button
              key={pill.key}
              type="button"
              onClick={() => onChange(pill.key)}
              className={cn(
                "inline-flex h-full cursor-pointer items-center gap-1.5 rounded-full px-3 text-[13px] leading-[18px] transition-colors duration-150",
                isActive
                  ? "bg-surface font-medium text-ink shadow-sm"
                  : "text-ink-muted hover:text-ink"
              )}
            >
              {pill.label}
              {pill.count !== undefined && (
                <span className={cn("text-[12px]", isActive ? "text-ink" : "text-ink-faint")}>
                  {pill.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {pills.map((pill) => {
        const isActive = pill.key === active;
        return (
          <button
            key={pill.key}
            type="button"
            onClick={() => onChange(pill.key)}
            className={cn(
              "inline-flex h-[34px] cursor-pointer items-center gap-1.5 rounded-full border px-3.5 text-[13px] leading-[18px] transition-colors duration-150",
              isActive
                ? "border-ink bg-ink text-surface"
                : "border-line bg-surface text-ink-muted hover:text-ink"
            )}
          >
            {pill.label}
            {pill.count !== undefined && (
              <span className={cn("text-[12px]", isActive ? "text-surface/70" : "text-ink-faint")}>
                {pill.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
