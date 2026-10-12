import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const storeMock = vi.hoisted(() => ({
  useNotifications: vi.fn(),
  useNotificationsLoading: vi.fn(),
  refreshNotifications: vi.fn(),
}));

const apiMock = vi.hoisted(() => ({
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  listNotifications: vi.fn(),
}));

vi.mock("@/lib/notificationStore", () => storeMock);
// Any api method the sidebar/page-header touches resolves to a stub —
// only the notifications calls are asserted.
vi.mock("@/lib/api", () => ({
  api: new Proxy(apiMock, {
    get: (target, prop) =>
      prop in target
        ? target[prop as keyof typeof target]
        : vi.fn(async () => []),
  }),
}));

import { Notifications } from "./Notifications";
import type { Notification } from "@/lib/types";

const ROW: Notification = {
  id: "n1",
  notification_type: "run_completed",
  severity: "success",
  title: "Done",
  message: "finished",
  action_path: null,
  entity_id: "r1",
  entity_type: "run",
  agent_id: null,
  agent_name: null,
  event_id: "e1",
  read: false,
  created_at: "2026-01-01T00:00:00Z",
};

function mount() {
  return render(
    <MemoryRouter>
      <Notifications />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }));
  vi.useFakeTimers({ shouldAdvanceTime: true });
  storeMock.useNotifications.mockReturnValue([ROW]);
  storeMock.useNotificationsLoading.mockReturnValue(false);
  apiMock.markNotificationRead.mockResolvedValue({ updated: true });
  apiMock.markAllNotificationsRead.mockResolvedValue({ updated: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("Notifications page (store-backed)", () => {
  it("renders rows from the store and never polls itself", async () => {
    mount();
    await act(async () => {});
    expect(screen.getByText("Done")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(30_000);
    // The page owns no interval — zero list calls regardless of clock.
    expect(apiMock.listNotifications).not.toHaveBeenCalled();
  });

  it("mark-read POSTs and triggers a store refresh, not a local GET", async () => {
    mount();
    await act(async () => {});
    const btn = screen.getAllByRole("button", { name: /mark as read/i })[0];
    fireEvent.click(btn);
    await act(async () => {});
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith("n1");
    expect(storeMock.refreshNotifications).toHaveBeenCalled();
    expect(apiMock.listNotifications).not.toHaveBeenCalled();
  });

  it("read-all POSTs and triggers a store refresh", async () => {
    mount();
    await act(async () => {});
    const btn = screen.getAllByRole("button", { name: /mark all as read/i })[0];
    fireEvent.click(btn);
    await act(async () => {});
    expect(apiMock.markAllNotificationsRead).toHaveBeenCalled();
    expect(storeMock.refreshNotifications).toHaveBeenCalled();
  });
});
