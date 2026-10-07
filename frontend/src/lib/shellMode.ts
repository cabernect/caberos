import { useSyncExternalStore } from "react";

/** How the app shell lays itself out: bottom tab bar, icon rail, or full sidebar. */
export type ShellMode = "phone" | "tablet" | "desktop";

/** Below this width the shell is a bottom tab bar (keep in sync with the @media rules in index.css). */
export const PHONE_MAX_WIDTH = 699;
/** Below this width (and above phone) the sidebar is forced to the icon rail. */
export const TABLET_MAX_WIDTH = 1099;

export function shellModeFor(width: number): ShellMode {
  if (width <= PHONE_MAX_WIDTH) return "phone";
  if (width <= TABLET_MAX_WIDTH) return "tablet";
  return "desktop";
}

const QUERIES = [`(max-width: ${PHONE_MAX_WIDTH}px)`, `(max-width: ${TABLET_MAX_WIDTH}px)`];

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const lists = QUERIES.map((query) => window.matchMedia(query));
  lists.forEach((list) => list.addEventListener("change", onChange));
  return () => lists.forEach((list) => list.removeEventListener("change", onChange));
}

function getSnapshot(): ShellMode {
  if (typeof window === "undefined") return "desktop";
  return shellModeFor(window.innerWidth);
}

/** Current shell mode; re-renders when the viewport crosses a breakpoint. */
export function useShellMode(): ShellMode {
  return useSyncExternalStore(subscribe, getSnapshot, () => "desktop");
}
