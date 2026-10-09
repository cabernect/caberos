import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

describe("DashboardSidebar on mobile", () => {
  it("opens the overlay even when the stored desktop preference is collapsed", () => {
    const navigate = vi.fn();
    const onToggle = vi.fn();
    render(
      <DashboardSidebar
        active="traces"
        onNavigate={navigate}
        onLogout={vi.fn()}
        collapsed
        onToggleCollapse={onToggle}
        agentCount={2}
      />,
    );
    fireEvent.click(screen.getByTitle("Expand sidebar"));
    expect(screen.getByTestId("sidebar-scrim")).toBeInTheDocument();
    expect(screen.getByTitle("Collapse sidebar")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sidebar-scrim"));
    expect(screen.queryByTestId("sidebar-scrim")).not.toBeInTheDocument();
    expect(onToggle).not.toHaveBeenCalled();
  });
});
