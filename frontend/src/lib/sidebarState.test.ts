import { beforeEach, describe, expect, it } from "vitest";
import { getStoredSidebarCollapsed, setStoredSidebarCollapsed } from "./sidebarState";

describe("dashboard sidebar state", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null before a preference is saved", () => {
    expect(getStoredSidebarCollapsed()).toBeNull();
  });

  it("persists collapsed and expanded states", () => {
    setStoredSidebarCollapsed(true);
    expect(getStoredSidebarCollapsed()).toBe(true);

    setStoredSidebarCollapsed(false);
    expect(getStoredSidebarCollapsed()).toBe(false);
  });

  it("ignores invalid stored values", () => {
    localStorage.setItem("caberos-sidebar-collapsed", "sometimes");
    expect(getStoredSidebarCollapsed()).toBeNull();
  });
});
