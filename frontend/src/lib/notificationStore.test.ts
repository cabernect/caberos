import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

// --- mocks ----------------------------------------------------------------

const { apiMock, crossTabMock, focusMock, prefsMock, adaptersMock } = vi.hoisted(() => ({
  apiMock: {
    listNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    reportDelivery: vi.fn(),
    failedDeliveries: vi.fn(),
    streamNotifications: vi.fn(),
    getNotificationPrefs: vi.fn(),
  },
  crossTabMock: {
    startCrossTab: vi.fn(),
    stopCrossTab: vi.fn(),
    isLeader: vi.fn(),
    onLeaderChange: vi.fn<(cb: (v: boolean) => void) => () => void>(() => () => {}),
    broadcastNotification: vi.fn(),
    onNotification: vi.fn<(cb: (n: Notification) => void) => () => void>(() => () => {}),
    onPrefsChanged: vi.fn<(cb: () => void) => () => void>(() => () => {}),
    selfTabVisible: vi.fn(),
    anyPeerVisible: vi.fn(),
  },
  focusMock: { isSuppressed: vi.fn() },
  prefsMock: {
    loadNotificationPrefs: vi.fn(),
    surfaceEnabled: vi.fn(),
    inQuietHours: vi.fn(),
  },
  adaptersMock: {
    deliverOs: vi.fn(),
    osAdapter: vi.fn(),
  },
}));

vi.mock("./api", () => ({ api: apiMock }));
vi.mock("./crossTab", () => crossTabMock);
vi.mock("./focusRegistry", () => focusMock);
vi.mock("./notificationPrefs", () => prefsMock);
vi.mock("./notifAdapters", () => adaptersMock);

import {
  refreshNotifications,
  useNotifications,
  useNotificationToasts,
} from "./notificationStore";
import type { Notification } from "./types";

function notif(partial: Partial<Notification>): Notification {
  return {
    id: `n-${Math.random().toString(36).slice(2, 8)}`,
    notification_type: "run_failed",
    severity: "error",
    title: "Run failed",
    message: "boom",
    action_path: null,
    entity_id: "r1",
    entity_type: "run",
    agent_id: null,
    agent_name: null,
    event_id: "e1",
    read: false,
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

async function flush(ms = 5) {
  await new Promise((r) => setTimeout(r, ms));
}

const unmounters: Array<() => void> = [];

function mountToasts() {
  const h = renderHook(() => useNotificationToasts());
  unmounters.push(h.unmount);
  return h;
}
function mountInbox() {
  const h = renderHook(() => useNotifications());
  unmounters.push(h.unmount);
  return h;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  apiMock.listNotifications.mockResolvedValue([]);
  apiMock.markNotificationRead.mockResolvedValue({ updated: true });
  apiMock.reportDelivery.mockResolvedValue({ recorded: true });
  apiMock.failedDeliveries.mockResolvedValue([]);
  // An SSE generator that never yields — tests drive events via poll.
  apiMock.streamNotifications.mockImplementation(async function* () {
    await new Promise(() => {});
  });
  prefsMock.loadNotificationPrefs.mockResolvedValue({});
  prefsMock.surfaceEnabled.mockImplementation((_t: string, s: string) => s === "toast");
  prefsMock.inQuietHours.mockReturnValue(false);
  focusMock.isSuppressed.mockReturnValue(false);
  crossTabMock.isLeader.mockReturnValue(true);
  crossTabMock.selfTabVisible.mockReturnValue(true);
  crossTabMock.anyPeerVisible.mockReturnValue(false);
  adaptersMock.deliverOs.mockResolvedValue({ state: "delivered" });
  adaptersMock.osAdapter.mockReturnValue("browser");
});

afterEach(() => {
  // Unmount everything → refCount hits 0 → store stops + state resets.
  while (unmounters.length) unmounters.pop()!();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("delivery coordinator", () => {
  it("fresh unread notification toasts + reports delivered on enabled surfaces", async () => {
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([]) // baseline
      .mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    expect(toasts.result.current.map((t) => t.id)).toContain(item.id);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id, "toast", "delivered", undefined,
    );
  });

  it("focus suppression kills toast + auto-reads, but OS ping still fires", async () => {
    focusMock.isSuppressed.mockReturnValue(true);
    prefsMock.surfaceEnabled.mockImplementation(() => true); // everything on
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    expect(toasts.result.current).toHaveLength(0); // no toast
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "toast", "suppressed", undefined);
    // OS adapter bypasses focus suppression — the ping is the completion
    // signal even when you're already on the page.
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "browser", "delivered", undefined);
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(item.id);
    expect(inbox.result.current.some((n) => n.id === item.id)).toBe(true); // recorded
  });

  it("quiet hours suppress pings but keep the row unread", async () => {
    prefsMock.inQuietHours.mockReturnValue(true);
    const item = notif({});
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    expect(toasts.result.current).toHaveLength(0);
    expect(apiMock.markNotificationRead).not.toHaveBeenCalled(); // stays unread
  });

  it("quiet hours do NOT silence approval_required — a blocked run must not stall silently", async () => {
    prefsMock.inQuietHours.mockReturnValue(true);
    prefsMock.surfaceEnabled.mockImplementation((_t: string, s: string) => s !== "inbox");
    const item = notif({ notification_type: "approval_required", severity: "warning" });
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    expect(toasts.result.current).toHaveLength(1);
    expect(adaptersMock.deliverOs).toHaveBeenCalled();
    expect(apiMock.markNotificationRead).not.toHaveBeenCalled();
  });

  it("follower tab renders toast but never reports or fires OS adapter", async () => {
    crossTabMock.isLeader.mockReturnValue(false);
    const item = notif({});
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    expect(toasts.result.current.map((t) => t.id)).toContain(item.id); // still toasts
    expect(apiMock.reportDelivery).not.toHaveBeenCalled(); // leader reports
    expect(adaptersMock.deliverOs).not.toHaveBeenCalled();
  });

  it("leader gossips each SSE event so followers don't need their own stream", async () => {
    const item = notif({});
    apiMock.streamNotifications.mockImplementation(async function* () {
      yield item;
      await new Promise(() => {}); // stream stays open
    });
    const toasts = mountToasts();
    mountInbox();
    await flush();
    await flush(20);
    expect(toasts.result.current.map((t) => t.id)).toContain(item.id);
    expect(crossTabMock.broadcastNotification).toHaveBeenCalledWith(item);
  });

  it("follower never opens the SSE socket", async () => {
    crossTabMock.isLeader.mockReturnValue(false);
    apiMock.listNotifications.mockResolvedValue([]);
    mountInbox();
    await flush(20);
    expect(apiMock.streamNotifications).not.toHaveBeenCalled();
  });

  it("OS surface fires only on the leader and reports outcome", async () => {
    prefsMock.surfaceEnabled.mockImplementation(() => true);
    const item = notif({});
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    mountInbox();
    await flush();
    refreshNotifications();
    await flush(20);
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "browser", "delivered", undefined);
  });

  it("OS adapter failure reports failed — retry comes from failedDeliveries", async () => {
    prefsMock.surfaceEnabled.mockImplementation(() => true);
    adaptersMock.deliverOs.mockResolvedValue({ state: "failed", error: "denied" });
    const item = notif({});
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    apiMock.failedDeliveries.mockResolvedValue([
      { notification: item, adapter: "browser", attempts: 1 },
    ]);
    mountInbox();
    await flush();
    refreshNotifications();
    await flush(20);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "browser", "failed", "denied");
    // Startup retry ran once more against the same adapter.
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(2);
    // Successful adapters are never retried — toast delivered exactly once.
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "toast", "delivered", undefined);
  });

  it("promotion to leader reports items poll-seen as follower (B38)", async () => {
    let leaderCb: ((v: boolean) => void) | undefined;
    crossTabMock.onLeaderChange.mockImplementation((cb: (v: boolean) => void) => {
      leaderCb = cb;
      return () => {};
    });
    crossTabMock.isLeader.mockReturnValue(false); // starts as follower
    prefsMock.surfaceEnabled.mockImplementation(() => true); // toast + browser on
    const item = notif({});
    apiMock.listNotifications.mockResolvedValueOnce([]).mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    // Follower pass: toast shown, zero reports.
    expect(apiMock.reportDelivery).not.toHaveBeenCalled();
    expect(toasts.result.current.map((t) => t.id)).toContain(item.id);
    // Promotion → leader-side pass replays for still-unread items.
    leaderCb!(true);
    await flush(20);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "toast", "delivered", undefined);
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(item.id, "browser", "delivered", undefined);
    // No duplicate toast — this tab already rendered it.
    expect(toasts.result.current.filter((t) => t.id === item.id)).toHaveLength(1);
  });

  it("promotion skips items the user already read (B38)", async () => {
    let leaderCb: ((v: boolean) => void) | undefined;
    crossTabMock.onLeaderChange.mockImplementation((cb: (v: boolean) => void) => {
      leaderCb = cb;
      return () => {};
    });
    crossTabMock.isLeader.mockReturnValue(false);
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([]) // baseline
      .mockResolvedValueOnce([item]) // follower discovers it unread
      .mockResolvedValue([{ ...item, read: true }]); // read before promotion
    mountInbox();
    await flush();
    refreshNotifications();
    await flush();
    refreshNotifications(); // poll refreshes row → read:true
    await flush();
    leaderCb!(true);
    await flush(20);
    expect(apiMock.reportDelivery).not.toHaveBeenCalled();
    expect(adaptersMock.deliverOs).not.toHaveBeenCalled();
  });

  it("re-fetches prefs when a peer tab broadcasts a prefs change (B36)", async () => {
    let prefsCb: (() => void) | undefined;
    crossTabMock.onPrefsChanged.mockImplementation((cb: () => void) => {
      prefsCb = cb;
      return () => {};
    });
    apiMock.listNotifications.mockResolvedValue([]);
    mountInbox();
    await flush();
    expect(prefsMock.loadNotificationPrefs).toHaveBeenCalledTimes(1); // boot load
    prefsCb!();
    expect(prefsMock.loadNotificationPrefs).toHaveBeenCalledTimes(2); // gossip reload
  });

  it("read rows from the baseline never deliver", async () => {
    const item = notif({ read: true });
    apiMock.listNotifications.mockResolvedValue([item]);
    const toasts = mountToasts();
    mountInbox();
    await flush();
    expect(toasts.result.current).toHaveLength(0);
    expect(apiMock.reportDelivery).not.toHaveBeenCalled();
  });
});
