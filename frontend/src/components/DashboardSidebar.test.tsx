import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardSidebar } from "./DashboardSidebar";

vi.mock("@/lib/useMediaQuery", () => ({
  useMediaQuery: () => true,
}));
vi.mock("@/lib/sidebarState", () => ({
  getStoredSidebarCollapsed: () => true,
  setStoredSidebarCollapsed: vi.fn(),
}));
vi.mock("@/components/NotificationCenter", () => ({
  NotificationCenter: () => null,
}));
vi.mock("@/lib/platform", () => ({
  IS_MAC: true,
}));

afterEach(() => vi.unstubAllGlobals());

describe("DashboardSidebar on mobile", () => {
  it("keeps macOS window controls above both the rail and expanded brand", () => {
    vi.stubGlobal("__TAURI_INTERNALS__", {});
    render(
      <MemoryRouter>
        <DashboardSidebar
          active="today"
          onLogout={vi.fn()}
          onToggleCollapse={vi.fn()}
          collapsed
        />
      </MemoryRouter>,
    );
    const railSpacer = screen.getByTestId("mac-titlebar-spacer");
    expect(railSpacer.parentElement?.firstElementChild).toBe(railSpacer);
    fireEvent.click(screen.getByTitle("Expand sidebar"));
    const expanded = screen.getByTitle("Collapse sidebar").closest("aside");
    expect(expanded?.firstElementChild).toHaveAttribute("data-testid", "mac-titlebar-spacer");
    expect(screen.getByText("CaberOS")).toBeInTheDocument();
  });

  it("opens the overlay even when the stored desktop preference is collapsed", () => {
    const navigate = vi.fn();
    const onToggle = vi.fn();
    render(
      <MemoryRouter>
        <DashboardSidebar
          active="traces"
          onNavigate={navigate}
          onLogout={vi.fn()}
          collapsed
          onToggleCollapse={onToggle}
          agentCount={2}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTitle("Expand sidebar"));
    expect(screen.getByTestId("sidebar-scrim")).toBeInTheDocument();
    expect(screen.getByTitle("Collapse sidebar")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sidebar-scrim"));
    expect(screen.queryByTestId("sidebar-scrim")).not.toBeInTheDocument();
    expect(onToggle).not.toHaveBeenCalled();
  });
});
