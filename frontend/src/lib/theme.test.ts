import { beforeEach, describe, expect, it } from "vitest";
import { applyTheme, getStoredThemeMode, resolveTheme } from "./themeState";

describe("theme state", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.classList.remove("dark");
  });

  it("defaults to system and resolves system preference", () => {
    expect(getStoredThemeMode()).toBe("system");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("persists valid theme modes and ignores invalid values", () => {
    localStorage.setItem("caberos-theme", "dark");
    expect(getStoredThemeMode()).toBe("dark");
    localStorage.setItem("caberos-theme", "sepia");
    expect(getStoredThemeMode()).toBe("system");
  });

  it("applies the resolved theme to the document root", () => {
    const resolved = applyTheme(document.documentElement, "dark", false);
    expect(resolved).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });
});
