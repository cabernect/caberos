import { IS_MAC } from "@/lib/platform";

/** Keep overlay traffic lights clear of sidebar content, using its own surface. */
export function MacTitlebarSpacer({ className }: { className?: string }) {
  if (!IS_MAC || !("__TAURI_INTERNALS__" in window)) return null;

  return (
    <div
      aria-hidden="true"
      data-tauri-drag-region
      data-testid="mac-titlebar-spacer"
      className={className}
      style={{ height: 32, width: "100%", flexShrink: 0 }}
    />
  );
}
