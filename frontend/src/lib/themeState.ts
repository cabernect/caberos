export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "caberos-theme";

export function getStoredThemeMode(storage: Storage | null = typeof window !== "undefined" ? window.localStorage : null): ThemeMode {
  const value = storage?.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): "light" | "dark" {
  return mode === "system" ? (prefersDark ? "dark" : "light") : mode;
}

export function applyTheme(root: HTMLElement, mode: ThemeMode, prefersDark: boolean): "light" | "dark" {
  const resolved = resolveTheme(mode, prefersDark);
  root.dataset.theme = resolved;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  return resolved;
}

export { STORAGE_KEY };
