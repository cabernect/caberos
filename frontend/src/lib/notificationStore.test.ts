import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

// --- mocks ----------------------------------------------------------------

const { apiMock, crossTabMock, focusMock, prefsMock, adaptersMock } =
  vi.hoisted(() => ({
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
      onLeaderChange: vi.fn<(cb: (v: boolean) => void) => () => void>(
        () => () => {},
      ),
      broadcastNotification: vi.fn(),
      broadcastInboxChanged: vi.fn(),
      onNotification: vi.fn<(cb: (n: Notification) => void) => () => void>(
        () => () => {},
      ),
      onPrefsChanged: vi.fn<(cb: () => void) => () => void>(() => () => {}),
      onInboxChanged: vi.fn<(cb: () => void) => () => void>(() => () => {}),
      selfTabVisible: vi.fn(),
      anyPeerVisible: vi.fn(),
    },
    focusMock: {
      isSuppressed: vi.fn(),
      getFocusedEntities: vi.fn<() => string[]>(() => []),
      notificationKeys: vi.fn<(n: Notification) => string[]>(() => []),
    },
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
  markReadForFocusedEntities,
  refreshNotifications,
  useNotifications,
  useNotificationsLoading,
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
  prefsMock.surfaceEnabled.mockImplementation(
    (_t: string, s: string) => s === "toast",
  );
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
      item.id,
      "toast",
      "delivered",
      undefined,
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
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "toast",
      "suppressed",
      undefined,
    );
    // OS adapter bypasses focus suppression — the ping is the completion
    // signal even when you're already on the page.
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "browser",
      "delivered",
      undefined,
    );
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(item.id);
    expect(inbox.result.current.some((n) => n.id === item.id)).toBe(true); // recorded
  });

  it("focus sweep retro-reads an unread row whose entity is now being viewed", async () => {
    // Landed while the window was unfocused → not suppressed, stays unread.
    // When the view registers the entity, the sweep reads it (B40 backfill).
    const item = notif({ entity_type: "session", entity_id: "s9" });
    focusMock.notificationKeys.mockReturnValue(["session:s9"]);
    apiMock.listNotifications.mockResolvedValue([item]); // baseline, pre-watch
    const inbox = mountInbox();
    await flush();
    expect(apiMock.markNotificationRead).not.toHaveBeenCalled();

    markReadForFocusedEntities(["agent:a1", "session:s9"]);
    await flush();
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(item.id);
    const row = inbox.result.current.find((n) => n.id === item.id);
    expect(row?.read).toBe(true); // row stays listed; flag flips
  });

  it("window refocus sweeps unread rows for already-registered entities", async () => {
    const item = notif({ entity_type: "session", entity_id: "s9" });
    focusMock.notificationKeys.mockReturnValue(["session:s9"]);
    focusMock.getFocusedEntities.mockReturnValue(["session:s9"]);
    apiMock.listNotifications.mockResolvedValue([item]);
    mountInbox();
    await flush();
    expect(apiMock.markNotificationRead).not.toHaveBeenCalled();

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await flush();
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(item.id);
  });

  it("focus sweep leaves unrelated unread rows alone", async () => {
    const item = notif({ entity_type: "session", entity_id: "other" });
    focusMock.notificationKeys.mockReturnValue(["session:other"]);
    apiMock.listNotifications.mockResolvedValue([item]);
    mountInbox();
    await flush();
    markReadForFocusedEntities(["session:s9"]);
    await flush();
    expect(apiMock.markNotificationRead).not.toHaveBeenCalled();
  });

  it("quiet hours suppress pings but keep the row unread", async () => {
    prefsMock.inQuietHours.mockReturnValue(true);
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
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
    prefsMock.surfaceEnabled.mockImplementation(
      (_t: string, s: string) => s !== "inbox",
    );
    const item = notif({
      notification_type: "approval_required",
      severity: "warning",
    });
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
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
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
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
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
    mountInbox();
    await flush();
    refreshNotifications();
    await flush(20);
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "browser",
      "delivered",
      undefined,
    );
  });

  it("OS adapter failure reports failed — retry comes from failedDeliveries", async () => {
    prefsMock.surfaceEnabled.mockImplementation(() => true);
    adaptersMock.deliverOs.mockResolvedValue({
      state: "failed",
      error: "denied",
    });
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
    apiMock.failedDeliveries.mockResolvedValue([
      { notification: item, adapter: "browser", attempts: 1 },
    ]);
    mountInbox();
    await flush();
    refreshNotifications();
    await flush(20);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "browser",
      "failed",
      "denied",
    );
    // Startup retry ran once more against the same adapter.
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(2);
    // Successful adapters are never retried — toast delivered exactly once.
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "toast",
      "delivered",
      undefined,
    );
  });

  it("promotion to leader reports items poll-seen as follower (B38)", async () => {
    let leaderCb: ((v: boolean) => void) | undefined;
    crossTabMock.onLeaderChange.mockImplementation(
      (cb: (v: boolean) => void) => {
        leaderCb = cb;
        return () => {};
      },
    );
    crossTabMock.isLeader.mockReturnValue(false); // starts as follower
    prefsMock.surfaceEnabled.mockImplementation(() => true); // toast + browser on
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
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
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "toast",
      "delivered",
      undefined,
    );
    expect(adaptersMock.deliverOs).toHaveBeenCalledTimes(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "browser",
      "delivered",
      undefined,
    );
    // No duplicate toast — this tab already rendered it.
    expect(toasts.result.current.filter((t) => t.id === item.id)).toHaveLength(
      1,
    );
  });

  it("promotion skips items the user already read (B38)", async () => {
    let leaderCb: ((v: boolean) => void) | undefined;
    crossTabMock.onLeaderChange.mockImplementation(
      (cb: (v: boolean) => void) => {
        leaderCb = cb;
        return () => {};
      },
    );
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

describe("SSE-first polling (B41)", () => {
  it("disconnect falls back to polling; reconnect HELLO stops it + one catch-up", async () => {
    // Attempt 1: HELLO then EOF — the loop backs off. Attempt 2: a held
    // (never-hello'd) pending stream — the fallback poll must tick while
    // it's unhealthy, and stop exactly when HELLO lands.
    let attempts = 0;
    let releaseSecond: (() => void) | null = null;
    const openSecond = () => releaseSecond?.();
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) => {
        attempts++;
        if (attempts === 1) {
          return (async function* () {
            onConnected?.();
            // EOF immediately → loop enters backoff.
          })();
        }
        return (async function* () {
          // HELLO waits on an externally-held promise — the attempt is
          // open but unhealthy until released.
          await new Promise<void>((r) => (releaseSecond = r));
          onConnected?.();
          await new Promise(() => {});
        })();
      },
    );
    mountInbox();
    await flush(20);
    // Baseline + the first HELLO catch-up have settled — record N.
    const n = apiMock.listNotifications.mock.calls.length;
    expect(n).toBeGreaterThan(0);
    // Attempt 2 opened at the 3 s backoff but is still pending HELLO —
    // the 5 s fallback tick fires exactly once per window.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await flush(20);
    expect(apiMock.listNotifications.mock.calls.length).toBe(n + 1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await flush(20);
    expect(apiMock.listNotifications.mock.calls.length).toBe(n + 2);
    // Second attempt's HELLO lands → one catch-up, then silence.
    await act(async () => {
      openSecond();
    });
    await flush(30);
    expect(apiMock.listNotifications.mock.calls.length).toBe(n + 3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    await flush();
    expect(apiMock.listNotifications.mock.calls.length).toBe(n + 3);
    expect(attempts).toBe(2); // exactly two stream attempts total
  });

  it("server invalidation triggers one coalesced snapshot — not a poll loop", async () => {
    let onChanged: (() => void) | undefined;
    apiMock.streamNotifications.mockImplementation(
      (
        _s: AbortSignal,
        onConnected?: () => void,
        onInboxChanged?: () => void,
      ) => {
        onChanged = onInboxChanged;
        return (async function* () {
          onConnected?.();
          await new Promise(() => {});
        })();
      },
    );
    mountInbox();
    await flush(20);
    const before = apiMock.listNotifications.mock.calls.length;
    onChanged?.();
    onChanged?.(); // second while in flight → coalesced, not doubled
    await flush(30);
    const extra = apiMock.listNotifications.mock.calls.length - before;
    expect(extra).toBeGreaterThanOrEqual(1);
    expect(extra).toBeLessThanOrEqual(2); // in-flight + at most one coalesced pass
  });

  it("follower never runs a periodic poll", async () => {
    crossTabMock.isLeader.mockReturnValue(false);
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) =>
        (async function* () {
          onConnected?.();
          await new Promise(() => {});
        })(),
    );
    mountInbox();
    await flush(20);
    const before = apiMock.listNotifications.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    await flush();
    expect(apiMock.listNotifications.mock.calls.length).toBe(before);
  });

  it("demote→promote inside backoff keeps exactly one live stream", async () => {
    let leaderCb: (v: boolean) => void = () => {};
    crossTabMock.onLeaderChange.mockImplementation((cb) => {
      leaderCb = cb;
      return () => {};
    });
    let streamCalls = 0;
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) => {
        streamCalls++;
        // First attempt EOFs immediately → the loop enters its 3 s backoff;
        // a demote+promote inside that window must not let the OLD loop
        // resolve its sleep into a third stream.
        if (streamCalls === 1) {
          return (async function* () {})(); // ends instantly → backoff
        }
        return (async function* () {
          onConnected?.(); // new owner gets a healthy stream
          await new Promise(() => {});
        })();
      },
    );
    mountInbox();
    await flush(20);
    expect(streamCalls).toBe(1);
    // Same synchronous turn — the old loop is mid-sleep.
    leaderCb(false);
    leaderCb(true);
    await flush();
    expect(streamCalls).toBe(2); // only the promotion opened a new attempt
    await vi.advanceTimersByTimeAsync(3_000);
    await flush();
    expect(streamCalls).toBe(2); // the dead backoff never resurrected
    const getsAfterHello = apiMock.listNotifications.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    await flush();
    expect(streamCalls).toBe(2);
    expect(apiMock.listNotifications.mock.calls.length).toBe(getsAfterHello);
  });

  it("stale response from a stopped epoch can't clobber a remount", async () => {
    let resolveOld: ((v: Notification[]) => void) | null = null;
    const finishOld = (rows: Notification[]) => resolveOld?.(rows);
    apiMock.listNotifications
      .mockImplementationOnce(() => new Promise((r) => (resolveOld = r)))
      .mockResolvedValue([notif({ id: "n-new" })]);
    const h1 = mountInbox();
    await flush(5); // request in flight (unresolved)
    h1.unmount(); // stop → old gen dead
    const h2 = mountInbox(); // fresh epoch → own fetch
    await flush(20);
    finishOld([notif({ id: "n-old" })]); // stale lands — must be ignored
    await flush(20);
    expect(h2.result.current.map((x) => x.id)).toContain("n-new");
    expect(h2.result.current.map((x) => x.id)).not.toContain("n-old");
  });

  it("failed initial snapshot still clears loading for the page", async () => {
    apiMock.listNotifications.mockRejectedValue(new Error("down"));
    const loading = renderHook(() => useNotificationsLoading());
    unmounters.push(loading.unmount);
    mountInbox();
    await flush(30);
    // Public contract — the page stops spinning even when the first
    // fetch dies.
    expect(loading.result.current).toBe(false);
  });

  it("SSE row delivered during an in-flight GET survives the response merge", async () => {
    let resolveOld: ((v: Notification[]) => void) | null = null;
    const finishOld = (rows: Notification[]) => resolveOld?.(rows);
    apiMock.listNotifications
      .mockImplementationOnce(() => new Promise((r) => (resolveOld = r)))
      .mockResolvedValue([]);
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) =>
        (async function* () {
          onConnected?.();
          await new Promise(() => {});
        })(),
    );
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush(20); // baseline resolved + hello catch-up in flight
    // A live row lands while the catch-up response is still pending —
    // drive it through the same public callback the stream uses.
    const live = notif({ id: "n-live" });
    const cb = crossTabMock.onNotification.mock.calls[0]?.[0];
    cb?.(live);
    finishOld([]); // stale response predates the live row
    await flush(30);
    expect(inbox.result.current.map((x) => x.id)).toContain("n-live");
    // One row, one toast, one delivery report — never re-processed by the
    // stale response or the coalesced follow-up.
    expect(inbox.result.current.filter((x) => x.id === "n-live")).toHaveLength(
      1,
    );
    expect(toasts.result.current.filter((t) => t.id === "n-live")).toHaveLength(
      1,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === "n-live" && c[1] === "toast",
      ),
    ).toHaveLength(1);
    // The coalesced follow-up GET carries the row forward in cache.
    expect(apiMock.listNotifications.mock.calls.length).toBeGreaterThanOrEqual(
      2,
    );
  });

  it("focused auto-read broadcast reaches peers after the ack", async () => {
    focusMock.isSuppressed.mockReturnValue(true);
    const item = notif({});
    apiMock.listNotifications
      .mockResolvedValueOnce([])
      .mockResolvedValue([item]);
    mountInbox();
    await flush(20);
    refreshNotifications();
    await flush(30);
    // markRead's POST resolved → cross-tab nudge broadcast.
    expect(crossTabMock.broadcastInboxChanged).toHaveBeenCalled();
  });

  it("offline → online: one retry per 3s backoff, delivery once after HELLO", async () => {
    let attempts = 0;
    const delivered: Notification[] = [];
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) => {
        attempts++;
        if (attempts <= 3) {
          // Network refusal / 502 — the attempt rejects before HELLO.
          return (async function* () {
            throw new Error("ECONNREFUSED");
          })();
        }
        return (async function* () {
          onConnected?.();
          const live = notif({ id: "n-online" });
          delivered.push(live);
          yield live;
          await new Promise(() => {});
        })();
      },
    );
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush(20);
    expect(attempts).toBe(1); // first rejection
    // Backoff spacing — exactly one new attempt per ~3 s window.
    await vi.advanceTimersByTimeAsync(3_000);
    await flush(20);
    expect(attempts).toBe(2);
    await vi.advanceTimersByTimeAsync(3_000);
    await flush(20);
    expect(attempts).toBe(3);
    await vi.advanceTimersByTimeAsync(3_000);
    await flush(30);
    expect(attempts).toBe(4); // fourth attempt connects
    await flush(30);
    // HELLO'd stream delivers the row exactly once across all surfaces.
    expect(inbox.result.current.map((x) => x.id)).toContain("n-online");
    expect(
      toasts.result.current.filter((t) => t.id === "n-online"),
    ).toHaveLength(1);
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === "n-online" && c[1] === "toast",
      ),
    ).toHaveLength(1);
    // Healthy now — idle for 15 s: no new attempts, no repeated GETs.
    const gets = apiMock.listNotifications.mock.calls.length;
    const tries = attempts;
    await vi.advanceTimersByTimeAsync(15_000);
    await flush();
    expect(attempts).toBe(tries);
    expect(apiMock.listNotifications.mock.calls.length).toBe(gets);
  });

  it("stop during pending prefs start leaves no timers or sockets", async () => {
    let resolvePrefs: ((v: unknown) => void) | null = null;
    const finishPrefs = () => resolvePrefs?.({});
    prefsMock.loadNotificationPrefs.mockImplementation(
      () => new Promise((r) => (resolvePrefs = r)),
    );
    const h = renderHook(() => useNotifications());
    unmounters.push(h.unmount);
    h.unmount(); // stop before prefs resolves
    finishPrefs();
    await flush(20);
    expect(apiMock.streamNotifications).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(apiMock.listNotifications).not.toHaveBeenCalled();
  });
  it("healthy SSE stream does not poll — idle for 30s after hello", async () => {
    // New contract: the stream's onConnected callback reports HELLO;
    // while healthy, NO recurring GET must run.
    apiMock.streamNotifications.mockImplementation(
      (_signal: AbortSignal, onConnected?: () => void) =>
        (async function* () {
          onConnected?.(); // HELLO
          await new Promise(() => {}); // healthy, never ends
        })(),
    );
    mountInbox();
    await flush(20);
    const callsAfterBaseline = apiMock.listNotifications.mock.calls.length;
    expect(callsAfterBaseline).toBeGreaterThan(0); // baseline happened
    await vi.advanceTimersByTimeAsync(30_000);
    await flush();
    // Healthy stream → zero additional snapshots for 30 s.
    expect(apiMock.listNotifications.mock.calls.length).toBe(
      callsAfterBaseline,
    );
  });
});

describe("subscribe-transition gap repro (H04)", () => {
  // Deterministic driver: attempt 1 HELLOs then closes (or rejects); the
  // reconnect attempt waits on an externally-held promise before HELLO.
  // A gap item is created AFTER mount but emitted server-side during the
  // subscribe transition — it must surface exactly once via catch-up.

  it("A: established-session reconnect — HELLO catch-up delivers the gap item once", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    let attempts = 0;
    let releaseSecond: (() => void) | null = null;
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) => {
        attempts++;
        if (attempts === 1) {
          return (async function* () {
            onConnected?.(); // healthy HELLO
            // then EOF → loop enters reconnect backoff
          })();
        }
        return (async function* () {
          await new Promise<void>((r) => (releaseSecond = r));
          onConnected?.(); // reconnect HELLO
          await new Promise(() => {}); // stays open
        })();
      },
    );
    const item = notif({ id: "n-gap-a", created_at: "2026-10-13T04:00:01Z" });
    apiMock.listNotifications
      .mockResolvedValueOnce([]) // baseline
      .mockResolvedValueOnce([]) // first-HELLO catch-up — predates the emit
      .mockResolvedValue([item]); // reconnect catch-up sees the gap item
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush(20);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    await flush(20);
    expect(attempts).toBe(2); // reconnect attempt opened, HELLO pending
    await act(async () => {
      releaseSecond?.();
    });
    await flush(30);
    expect(toasts.result.current.filter((t) => t.id === item.id)).toHaveLength(
      1,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === item.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      item.id,
      "toast",
      "delivered",
      undefined,
    );
    expect(apiMock.markNotificationRead).not.toHaveBeenCalledWith(item.id);
    expect(inbox.result.current.some((n) => n.id === item.id)).toBe(true);
    // A repeat refresh must not re-toast or re-report.
    refreshNotifications();
    await flush(20);
    expect(toasts.result.current.filter((t) => t.id === item.id)).toHaveLength(
      1,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === item.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
  });

  it("B: initial fetch+stream fail offline, then recovery delivers the gap item once", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    let attempts = 0;
    let releaseSecond: (() => void) | null = null;
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) => {
        attempts++;
        if (attempts === 1) {
          return (async function* () {
            throw new Error("backend offline");
          })();
        }
        return (async function* () {
          await new Promise<void>((r) => (releaseSecond = r));
          onConnected?.();
          await new Promise(() => {});
        })();
      },
    );
    const gap = notif({ id: "n-gap-b", created_at: "2026-10-13T04:00:01Z" });
    const old = notif({ id: "n-old-b", created_at: "2026-10-12T00:00:00Z" });
    apiMock.listNotifications
      .mockRejectedValueOnce(new Error("backend offline")) // initial baseline
      .mockResolvedValue([old, gap]); // catch-up sees both
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush(20);
    expect(attempts).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    await flush(20);
    expect(attempts).toBe(2); // reconnect opened, HELLO held
    await act(async () => {
      releaseSecond?.();
    });
    await flush(30);
    expect(toasts.result.current.filter((t) => t.id === gap.id)).toHaveLength(
      1,
    );
    const gapReports = apiMock.reportDelivery.mock.calls.filter(
      (c) => c[0] === gap.id && c[1] === "toast",
    );
    expect(gapReports).toHaveLength(1);
    expect(apiMock.reportDelivery).toHaveBeenCalledWith(
      gap.id,
      "toast",
      "delivered",
      undefined,
    );
    // Historical row must not toast and must never be reported.
    expect(toasts.result.current.filter((t) => t.id === old.id)).toHaveLength(
      0,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter((c) => c[0] === old.id),
    ).toHaveLength(0);
    expect(apiMock.markNotificationRead).not.toHaveBeenCalledWith(gap.id);
    expect(inbox.result.current.some((n) => n.id === gap.id)).toBe(true);
    // Repeat catch-up refresh — still exactly one delivery.
    refreshNotifications();
    await flush(20);
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === gap.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
  });

  it("C: in-flight baseline overlap — server-returned gap item delivered once", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    let resolveBaseline: ((v: Notification[]) => void) | null = null;
    const finishBaseline = (rows: Notification[]) => resolveBaseline?.(rows);
    apiMock.streamNotifications.mockImplementation(
      (_s: AbortSignal, onConnected?: () => void) =>
        (async function* () {
          onConnected?.(); // HELLO lands while baseline fetch is pending
          await new Promise(() => {});
        })(),
    );
    const old = notif({ id: "n-old-c", created_at: "2026-10-12T00:00:00Z" });
    const gap = notif({ id: "n-gap-c", created_at: "2026-10-13T04:00:01Z" });
    apiMock.listNotifications
      .mockImplementationOnce(() => new Promise((r) => (resolveBaseline = r)))
      .mockResolvedValue([old, gap]); // committed rows persist in follow-ups
    const toasts = mountToasts();
    const inbox = mountInbox();
    await flush(20); // HELLO + catch-up queued behind the held baseline
    // The baseline response carries the row the server emitted during the
    // subscribe transition — no SSE frame ever arrives for it.
    finishBaseline([old, gap]);
    await flush(30);
    // Healthy-pipeline control: a later pushed item does toast.
    const control = notif({
      id: "n-live-c",
      created_at: "2026-10-13T04:00:02Z",
    });
    const cb = crossTabMock.onNotification.mock.calls[0]?.[0];
    cb?.(control);
    await flush(20);
    expect(toasts.result.current.filter((t) => t.id === control.id)).toHaveLength(
      1,
    );
    // The gap item must be delivered exactly once — not lost to the
    // baseline's "already present" semantics.
    expect(toasts.result.current.filter((t) => t.id === gap.id)).toHaveLength(
      1,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === gap.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
    expect(toasts.result.current.filter((t) => t.id === old.id)).toHaveLength(
      0,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter((c) => c[0] === old.id),
    ).toHaveLength(0);
    expect(inbox.result.current.some((n) => n.id === gap.id)).toBe(true);
    refreshNotifications();
    await flush(20);
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === gap.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
  });

  it("D: baseline read:true row never reports even when timestamp is fresh", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    const readFresh = notif({
      id: "n-read-fresh",
      created_at: "2026-10-13T04:00:01Z",
      read: true,
    });
    apiMock.listNotifications.mockResolvedValue([readFresh]);
    mountToasts();
    mountInbox();
    await flush(30);
    expect(apiMock.reportDelivery).not.toHaveBeenCalled();
  });

  it("E: unparseable created_at is treated as historical, never delivered", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    const bad = notif({ id: "n-baddate", created_at: "not-a-date" });
    apiMock.listNotifications.mockResolvedValue([bad]);
    mountToasts();
    mountInbox();
    await flush(30);
    expect(apiMock.reportDelivery).not.toHaveBeenCalled();
    // Still lands in the inbox as a row — suppressed from delivery, not data.
  });

  it("F: same-millisecond created_at as watch start is treated as fresh", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    const sameMs = notif({
      id: "n-samems",
      created_at: new Date(Date.now()).toISOString(),
    });
    apiMock.listNotifications.mockResolvedValue([sameMs]);
    const toasts = mountToasts();
    mountInbox();
    await flush(30);
    expect(toasts.result.current.filter((t) => t.id === sameMs.id)).toHaveLength(
      1,
    );
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === sameMs.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
  });

  it("G: UTC-offset created_at parses to the same instant", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    const offset = notif({
      id: "n-offset",
      created_at: "2026-10-13T13:00:01+09:00", // == 04:00:01Z
    });
    apiMock.listNotifications.mockResolvedValue([offset]);
    const toasts = mountToasts();
    mountInbox();
    await flush(30);
    expect(toasts.result.current.filter((t) => t.id === offset.id)).toHaveLength(
      1,
    );
  });

  it("H: fresh baseline row on a follower toasts, then promotion reports once (no dup)", async () => {
    vi.setSystemTime("2026-10-13T04:00:00Z");
    let leaderCb: ((v: boolean) => void) | undefined;
    crossTabMock.onLeaderChange.mockImplementation(
      (cb: (v: boolean) => void) => {
        leaderCb = cb;
        return () => {};
      },
    );
    crossTabMock.isLeader.mockReturnValue(false);
    const fresh = notif({
      id: "n-fresh-follower",
      created_at: "2026-10-13T04:00:01Z",
    });
    apiMock.listNotifications.mockResolvedValue([fresh]);
    const toasts = mountToasts();
    mountInbox();
    await flush(30);
    expect(toasts.result.current.filter((t) => t.id === fresh.id)).toHaveLength(
      1,
    );
    expect(apiMock.reportDelivery).not.toHaveBeenCalled(); // follower defers
    leaderCb!(true);
    await flush(30);
    expect(
      apiMock.reportDelivery.mock.calls.filter(
        (c) => c[0] === fresh.id && c[1] === "toast",
      ),
    ).toHaveLength(1);
    expect(toasts.result.current.filter((t) => t.id === fresh.id)).toHaveLength(
      1,
    );
  });
});
