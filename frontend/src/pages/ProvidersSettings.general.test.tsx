import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@/lib/theme";

const apiMock = vi.hoisted(() => ({
  listProviders: vi.fn(),
  me: vi.fn(),
  getDependencies: vi.fn(),
  recheckDependencies: vi.fn(),
  listDependencyJobs: vi.fn(),
  getNotificationPrefs: vi.fn(),
  getContextCapturePolicy: vi.fn(),
  updateContextCapturePolicy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: new Proxy(apiMock, {
    get: (target, prop) =>
      prop in target
        ? target[prop as keyof typeof target]
        : vi.fn(async () => []),
  }),
}));

vi.mock("@/lib/crossTab", () => ({
  startCrossTab: vi.fn(),
  stopCrossTab: vi.fn(),
  isLeader: vi.fn(() => true),
  onLeaderChange: vi.fn(() => () => {}),
  broadcastNotification: vi.fn(),
  broadcastInboxChanged: vi.fn(),
  onNotification: vi.fn(() => () => {}),
  onInboxChanged: vi.fn(() => () => {}),
  onPrefsChanged: vi.fn(() => () => {}),
  selfTabVisible: vi.fn(() => true),
  anyPeerVisible: vi.fn(() => false),
}));

vi.mock("@/lib/notificationStore", () => ({
  useNotifications: vi.fn(() => []),
  useNotificationsLoading: vi.fn(() => false),
  refreshNotifications: vi.fn(),
}));

const LOCAL_PREFS = {
  defaults: { toast: true, browser: false, system: false },
  overrides: {},
  quiet_hours: { enabled: false, start: "22:00", end: "07:00" },
};
vi.mock("@/lib/notificationPrefs", () => ({
  loadNotificationPrefs: vi.fn(async () => LOCAL_PREFS),
  surfaceEnabled: vi.fn(() => true),
  inQuietHours: vi.fn(() => false),
  getNotificationPrefs: vi.fn(() => LOCAL_PREFS),
  saveNotificationPrefs: vi.fn(async () => LOCAL_PREFS),
  onPrefsChange: vi.fn(() => () => {}),
  NOTIFICATION_TYPES: [],
}));

vi.mock("@/lib/notifAdapters", () => ({
  deliverOs: vi.fn(async () => ({ state: "delivered" })),
  osAdapter: vi.fn(() => "browser"),
  osPermissionState: vi.fn(async () => "default"),
  osNotificationAvailable: vi.fn(() => false),
}));

vi.mock("@/lib/focusRegistry", () => ({ isSuppressed: vi.fn(() => false) }));

vi.mock("@/lib/confirmHook", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), toast: vi.fn() }),
}));

import { ProvidersSettings } from "./ProvidersSettings";

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
  apiMock.listProviders.mockResolvedValue([]);
  apiMock.me.mockResolvedValue({
    id: "op",
    username: "admin",
    must_change_password: false,
  });
  apiMock.getDependencies.mockResolvedValue({ dependencies: [] });
  apiMock.recheckDependencies.mockResolvedValue({ dependencies: [] });
  apiMock.listDependencyJobs.mockResolvedValue({ jobs: [] });
  apiMock.getNotificationPrefs.mockResolvedValue({
    defaults: { toast: true, browser: false, system: false },
    overrides: {},
    quiet_hours: { enabled: false, start: "22:00", end: "07:00" },
  });
  apiMock.getContextCapturePolicy.mockResolvedValue({
    retention_days: 7,
    max_bytes: 268435456,
    max_payload_bytes: 1048576,
    pinned: { retention_days: false, max_bytes: false, max_payload_bytes: false },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("General settings (W11 internal catalog)", () => {
  it("renders no Model Catalog card or refresh controls — catalog is internal", async () => {
    render(
      <MemoryRouter>
        <ThemeProvider>
          <ProvidersSettings />
        </ThemeProvider>
      </MemoryRouter>,
    );
    await act(async () => {});
    expect(screen.queryByText("Model Catalog")).toBeNull();
    expect(screen.queryByText(/Refresh now/i)).toBeNull();
    expect(screen.queryByText(/Bundled snapshot/i)).toBeNull();
    expect(screen.queryByLabelText(/refresh catalog/i)).toBeNull();
    // Its sibling cards remain.
    expect(screen.getByText("Optional Tools & Runtimes")).toBeTruthy();
    expect(screen.getAllByText("Notifications").length).toBeGreaterThan(0);
  });

  it("installation-wide capture retention lives here, fetched on mount", async () => {
    apiMock.getContextCapturePolicy.mockResolvedValue({
      retention_days: 7,
      max_bytes: 268435456,
      max_payload_bytes: 1048576,
      pinned: { retention_days: false, max_bytes: false, max_payload_bytes: false },
    });
    render(
      <MemoryRouter>
        <ThemeProvider>
          <ProvidersSettings />
        </ThemeProvider>
      </MemoryRouter>,
    );
    await act(async () => {});
    // No agent selection needed — this is an installation policy, shown
    // directly in the section rather than behind a disclosure.
    expect(apiMock.getContextCapturePolicy).toHaveBeenCalled();
    expect(screen.getByLabelText(/Retention window/)).toBeTruthy();
  });
});
