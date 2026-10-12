import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";

// Public surface: the store's real transports, controlled.
const apiMock = vi.hoisted(() => ({
  gatewayHealth: vi.fn(),
  gatewayError: vi.fn(async () => null),
  me: vi.fn(async () => ({
    id: "op",
    username: "admin",
    must_change_password: false,
  })),
  listProviders: vi.fn(async () => []),
  listAgents: vi.fn(async () => []),
  listNotifications: vi.fn(async () => []),
  streamNotifications: vi.fn(),
  getNotificationPrefs: vi.fn(async () => ({
    defaults: {},
    overrides: {},
    quiet_hours: {},
  })),
  failedDeliveries: vi.fn(async () => []),
  reportDelivery: vi.fn(async () => ({})),
}));

vi.mock("@/lib/api", () => ({
  api: new Proxy(apiMock, {
    get: (target, prop) =>
      prop in target
        ? target[prop as keyof typeof target]
        : vi.fn(async () => []),
  }),
}));

// Heavy routes flattened — the store path under test stays real.
vi.mock("./pages/Login", () => ({ Login: () => null }));
vi.mock("./pages/AgentList", () => ({ AgentList: () => null }));
vi.mock("./pages/Conversation", () => ({ Conversation: () => null }));
vi.mock("./pages/ProvidersSettings", () => ({ ProvidersSettings: () => null }));
vi.mock("./pages/KnowledgeVault", () => ({ KnowledgeVault: () => null }));
vi.mock("./pages/Skills", () => ({ Skills: () => null }));
vi.mock("./pages/Scheduler", () => ({ Scheduler: () => null }));
vi.mock("./pages/Mcps", () => ({ Mcps: () => null }));
vi.mock("./pages/Channels", () => ({ Channels: () => null }));
vi.mock("./pages/Observability", () => ({ Observability: () => null }));
vi.mock("./pages/Traces", () => ({ Traces: () => null }));
vi.mock("./pages/Notifications", () => ({ Notifications: () => null }));

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

vi.mock("@/lib/notificationPrefs", () => ({
  loadNotificationPrefs: vi.fn(async () => ({
    defaults: { toast: true, browser: false, system: false },
    overrides: {},
    quiet_hours: { enabled: false, start: "22:00", end: "07:00" },
  })),
  surfaceEnabled: vi.fn(() => true),
  inQuietHours: vi.fn(() => false),
}));

vi.mock("@/lib/notifAdapters", () => ({
  deliverOs: vi.fn(async () => ({ state: "delivered" })),
  osAdapter: vi.fn(() => "browser"),
  osPermissionState: vi.fn(async () => "default"),
  osNotificationAvailable: vi.fn(() => false),
}));

vi.mock("@/lib/focusRegistry", () => ({ isSuppressed: vi.fn(() => false) }));

import App from "./App";

function flush(ms = 0) {
  return act(async () => {
    for (let i = 0; i < ms || i < 1; i++) await Promise.resolve();
  });
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
  apiMock.streamNotifications.mockImplementation(
    (_s: AbortSignal, onConnected?: () => void) =>
      (async function* () {
        onConnected?.(); // healthy HELLO — no reconnect churn
        await new Promise(() => {});
      })(),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("App cold start", () => {
  it("gateway pending → zero notification traffic; healthy → one stream, no idle GETs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let resolveHealth: (() => void) | null = null;
    apiMock.gatewayHealth.mockImplementationOnce(
      () => new Promise<void>((r) => (resolveHealth = r)),
    );
    render(<App />);
    await flush(20);
    // Backend not answering yet — the store must not have started.
    await vi.advanceTimersByTimeAsync(5_000);
    await flush();
    expect(apiMock.streamNotifications).not.toHaveBeenCalled();
    expect(apiMock.listNotifications).not.toHaveBeenCalled();
    expect(apiMock.failedDeliveries).not.toHaveBeenCalled();
    // Gateway answers → auth → toasts mount → leader stream opens.
    const fireHealth = () => resolveHealth?.();
    fireHealth();
    await flush(20);
    expect(apiMock.streamNotifications).toHaveBeenCalledTimes(1);
    expect(apiMock.failedDeliveries).toHaveBeenCalledTimes(1);
    const gets = apiMock.listNotifications.mock.calls.length;
    await vi.advanceTimersByTimeAsync(15_000);
    await flush();
    expect(apiMock.listNotifications.mock.calls.length).toBe(gets);
    expect(apiMock.streamNotifications).toHaveBeenCalledTimes(1);
  });
});
