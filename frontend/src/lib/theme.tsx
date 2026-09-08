import { useEffect, useMemo, useState, type ReactNode } from "react";
import { applyTheme, getStoredThemeMode, type ThemeMode } from "./themeState";
import { ThemeContext } from "./themeContext";

export type { ThemeMode } from "./themeState";

const STORAGE_KEY = "caberos-theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => getStoredThemeMode());
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setResolvedTheme(applyTheme(root, mode, media.matches));

    apply();
    if (mode === "system") media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [mode]);

  const setMode = (nextMode: ThemeMode) => {
    setModeState(nextMode);
    window.localStorage.setItem(STORAGE_KEY, nextMode);
  };

  const value = useMemo(() => ({ mode, resolvedTheme, setMode }), [mode, resolvedTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
