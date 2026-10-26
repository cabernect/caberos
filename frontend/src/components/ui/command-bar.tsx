import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { modShortcut } from "@/lib/platform";
import { OPEN_PALETTE_EVENT } from "@/components/CommandPalette";

/**
 * The "Search or run a command ⌘K / Ctrl+K" field shown at the top of pages.
 * It's a button — clicking opens the global CommandPalette.
 */
export function CommandBar({
  placeholder = "Search or run a command…",
  className,
}: {
  placeholder?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT))}
      className={cn(
        "flex h-10 w-full cursor-pointer items-center gap-2.5 rounded-md border border-line bg-surface px-3.5 text-left text-[14px] text-ink-faint transition-colors hover:border-ink-faint",
        className
      )}
    >
      <Search className="h-4 w-4 shrink-0" />
      <span className="flex-1 truncate">{placeholder}</span>
      <kbd className="rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
        {modShortcut("K")}
      </kbd>
    </button>
  );
}
