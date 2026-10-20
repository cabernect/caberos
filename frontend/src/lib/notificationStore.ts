/**
 * Notification store + delivery coordinator (W9).
 *
 * Pipeline: SSE event (5 s poll fallback) → suppression check → prefs
 * matrix → quiet hours → fire adapters → per-adapter delivery report.
 *
 * - The inbox always records; focus suppression only kills the toast and
 *   auto-marks the row read (you're already looking at the entity). The
 *   OS ping still fires while focused — it doubles as the completion
 *   signal even when you're on the page.
 * - Quiet hours suppress pings uniformly but leave the row unread — the
 *   badge/inbox still shows it when you return.
 * - One leader tab owns OS-surface delivery + all delivery reporting;
 *   every visible tab renders toasts.
 * - Failed adapters retry once on (re)connect, only while the row stays
 *   unread — a ping for something already read is worse than none.
 */

import { useSyncExternalStore } from "react";
import { api } from "./api";
import type { Notification } from "./types";
import {
  anyPeerVisible,
  broadcastInboxChanged,
  broadcastNotification,
  isLeader,
  onInboxChanged,
  onLeaderChange,
  onNotification,
  onPrefsChanged,
  selfTabVisible,
  startCrossTab,
  stopCrossTab,
} from "./crossTab";
import { getFocusedEntities, isSuppressed, notificationKeys } from "./focusRegistry";
import {
  inQuietHours,
  loadNotificationPrefs,
  surfaceEnabled,
} from "./notificationPrefs";
import { deliverOs, osAdapter } from "./notifAdapters";
import { notificationTarget } from "./notificationLinks";

const POLL_MS = 5_000;
const TOAST_DURATION_MS = 6_000;
const SSE_RECONNECT_MS = 3_000;

type Listener = () => void;

let notifications: Notification[] = [];
let toasts: Notification[] = [];
const listeners = new Set<Listener>();
let seenIds = new Set<string>();
let baselineDone = false;
// Wall time when this store session started — a delayed baseline response
// can contain events emitted after mount; only truly historical rows are
// marked seen without delivering.
let watchStartedAt = 0;
let refCount = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

let sseAbort: AbortController | null = null;
let sseRunning = false;
let sseHealthy = false; // HELLO seen on the current attempt
// Transport epoch — every SSE attempt, callback, retry and finalizer
// must re-check it. Without it, a demoted→promoted cycle re-arms an old
// loop's backoff into a second stream and a stale late-hello can kill a
// new owner's fallback.
let transportEpoch = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectResolve: (() => void) | null = null;
// In-flight snapshot ownership — a stopped/remounted store must never
// wait on or be clobbered by a previous epoch's request.
let activeRequest: { gen: number; ctrl: AbortController } | null = null;
// IDs delivered by SSE while a snapshot was in flight — the response
// predates them, so they're merged forward instead of overwritten.
let livePending = new Set<string>();
let leader = false;
// Lifecycle flag — an interval-id guard can't represent "the stream is
// healthy, no timer is running", and a second hook would double-start.
let running = false;
// Epoch — increments on start/stop so stale async results can't write
// into a restarted store.
let generation = 0;
// Fallback poll — sequential setTimeout chain (never setInterval).
let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
// Coalesced dirty pass — at most ONE extra snapshot when invalidations
// arrive while a fetch is in flight.
let dirtyAgain = false;
// First-snapshot gate for the page's loading UI.
let loading = true;
// Unread items this tab processed as a follower — a follower can't report
// deliveries, so seenIds alone would suppress the leader-side pass forever
// if the tab is later promoted (B38). On promotion each deferred id is
// re-processed for reporting only.
const deferredReports = new Set<string>();
let unsubLeader: (() => void) | null = null;
let unsubNotif: (() => void) | null = null;
let unsubPrefs: (() => void) | null = null;
let unsubInboxChanged: (() => void) | null = null;

// Router navigation for OS-notification clicks — registered by a mounted
// component (NotificationToasts) since the store lives outside React.
let navigateFn: ((path: string) => void) | null = null;
export function setNotificationNavigator(fn: (path: string) => void) {
  navigateFn = fn;
}

function navigateToNotification(n: Notification) {
  const path = notificationTarget(n);
  if (navigateFn) navigateFn(path);
  else window.location.assign(path);
}

function emit() {
  for (const cb of listeners) cb();
}

/** Every SSE callback/timer/frame checks this — a demoted, aborted or
 *  replaced attempt can never poke the new transport. */
function validTransport(gen: number, epoch: number): boolean {
  return sseRunning && current(gen) && leader && epoch === transportEpoch;
}

function cancelReconnect() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  reconnectResolve?.();
  reconnectResolve = null;
}

function report(
  n: Notification,
  adapter: string,
  state: string,
  error?: string,
) {
  api.reportDelivery(n.id, adapter, state, error).catch(() => {});
}

function markRead(n: Notification) {
  api
    .markNotificationRead(n.id)
    .then(() => broadcastInboxChanged()) // peers sync read-state too
    .catch(() => {});
  deferredReports.delete(n.id); // read rows never need pings or reports
  const row = notifications.find((x) => x.id === n.id);
  if (row) row.read = true;
}

/** Retro-read unread rows pointing at currently focused entities — the
 *  same rule arrival-time suppression applies, applied late: the operator
 *  was mid-run when the row landed, but they're looking at it now. */
function sweepReadsForKeys(keys: string[]) {
  if (!running || !keys.length) return;
  const focused = new Set(keys);
  let changed = false;
  for (const n of notifications) {
    if (!n.read && notificationKeys(n).some((k) => focused.has(k))) {
      markRead(n);
      changed = true;
    }
  }
  if (changed) emit();
}

/** Called by views when they register their focused entities. */
export function markReadForFocusedEntities(keys: string[]) {
  sweepReadsForKeys(keys);
}

function onWindowFocus() {
  sweepReadsForKeys(getFocusedEntities());
}

function showToast(n: Notification) {
  if (toasts.some((t) => t.id === n.id)) return;
  toasts = [...toasts, n];
  timers.set(
    n.id,
    setTimeout(() => dismissToast(n.id), TOAST_DURATION_MS),
  );
}

/** Leader-side toast accounting: a toast "delivered" if any visible tab
 *  rendered it, "suppressed" if none could. Disabled prefs → no row. */
function reportToastAggregate(n: Notification) {
  report(
    n,
    "toast",
    selfTabVisible() || anyPeerVisible() ? "delivered" : "suppressed",
  );
}

async function fireOsAdapter(n: Notification) {
  const outcome = await deliverOs(n, () => navigateToNotification(n));
  report(n, osAdapter(), outcome.state, outcome.error);
}

/**
 * Delivery pipeline for one fresh notification.
 * `fromBaseline`: poll-discovered items that arrived while SSE was down —
 * they go through the same pipeline so fallback delivery still works.
 */
/** Events that block a run until the operator answers — they pierce
 *  quiet hours (explicit per-type mutes still apply via surfaceEnabled). */
const HITL_TYPES = new Set(["approval_required", "elicitation_required"]);

function process(n: Notification, reportsOnly = false) {
  if (seenIds.has(n.id)) return;
  seenIds.add(n.id);
  if (activeRequest) livePending.add(n.id); // response predates this row
  notifications = [n, ...notifications.filter((x) => x.id !== n.id)];
  if (!leader && !n.read) deferredReports.add(n.id);
  else deferredReports.delete(n.id);

  const toastWanted = surfaceEnabled(n.notification_type, "toast");
  const osSurface = osAdapter();
  const osWanted = surfaceEnabled(n.notification_type, osSurface);

  // Two independent gates:
  // - focused = the exact entity is open in a focused tab — kills the
  //   toast + auto-reads (you're at the scene), but NOT the OS ping.
  // - quiet = quiet hours — kills both pings, row stays unread.
  //   Exception: HITL-blocking events (approval/elicitation) pierce quiet
  //   hours — suppressing them leaves a run silently stalled all night.
  //   An explicit per-type mute still wins via surfaceEnabled.
  const focused = !n.read && isSuppressed(n);
  const quiet =
    !n.read && inQuietHours() && !HITL_TYPES.has(n.notification_type);

  if (
    !n.read &&
    toastWanted &&
    !focused &&
    !quiet &&
    selfTabVisible() &&
    !reportsOnly
  ) {
    showToast(n);
  }
  if (leader && !n.read) {
    if (toastWanted) {
      if (focused || quiet) report(n, "toast", "suppressed");
      else reportToastAggregate(n);
    }
    if (osWanted) {
      if (quiet) report(n, osSurface, "suppressed");
      else void fireOsAdapter(n);
    }
  }
  if (focused) markRead(n);
  emit();
}

/** Retry previously-failed adapters once — only while unread. */
async function retryFailedDeliveries() {
  if (!leader) return;
  try {
    const failed = await api.failedDeliveries();
    for (const row of failed) {
      const n = row.notification;
      if (n.read) continue;
      if (row.adapter === osSurface()) await fireOsAdapter(n);
      else if (row.adapter === "toast" && selfTabVisible()) {
        showToast(n);
        report(n, "toast", "delivered");
      }
    }
  } catch {
    // Offline — next reconnect tries again.
  }
}
function osSurface(): "browser" | "system" {
  return osAdapter();
}

// Serialize every snapshot — an unbounded fetch would stack one socket
// per tick until the per-origin connection pool is gone
// (ERR_INSUFFICIENT_RESOURCES — B37). The fetch itself is also bounded.
function current(gen: number): boolean {
  return running && gen === generation;
}

async function fetchSnapshot(gen: number) {
  if (activeRequest?.gen === gen) {
    // An invalidation landed while a fetch was in flight — one coalesced
    // follow-up pass captures what the in-flight response can't see.
    dirtyAgain = true;
    return;
  }
  // A previous generation's hung request never blocks a remount.
  activeRequest?.ctrl.abort();
  const req = { gen, ctrl: new AbortController() };
  activeRequest = req;
  try {
    const signal = AbortSignal.any
      ? AbortSignal.any([req.ctrl.signal, AbortSignal.timeout(15_000)])
      : AbortSignal.timeout(15_000);
    const list = await api.listNotifications(false, signal);
    if (!current(gen) || activeRequest !== req) return; // stale response
    // Rows delivered live while this request flew are never clobbered
    // by a snapshot that predates them.
    const live = notifications.filter(
      (x) => livePending.has(x.id) && !list.some((l) => l.id === x.id),
    );
    const wasBaseline = !baselineDone;
    if (wasBaseline) {
      // First fetch is the baseline — but a delayed/failed initial fetch
      // can return rows created after this store mounted (the gap between
      // mount and the server's stream subscription). Those are live events,
      // not history — only genuinely historical rows are marked seen.
      for (const n of list) {
        const createdAt = Date.parse(n.created_at);
        if (n.read || !Number.isFinite(createdAt) || createdAt < watchStartedAt) {
          seenIds.add(n.id);
        }
      }
      baselineDone = true;
    }
    notifications = [...live, ...list];
    for (const n of notifications) {
      if (!n.read && !seenIds.has(n.id)) {
        process(n); // SSE-gap fallback
        // Followers must get the fresh frame as if the stream lived —
        // an invalidation alone would leave their ping undelivered.
        if (leader) broadcastNotification(n);
      }
    }
    // The baseline response may predate rows that arrived live while it
    // flew — keep livePending until a snapshot can actually see them.
    if (!wasBaseline) livePending.clear();
    loading = false;
    // A completed leader-side catch-up/fallback pass is the one truth
    // followers need — share it so they refresh once, without their own
    // backend traffic.
    if (leader) broadcastInboxChanged();
    emit();
  } catch {
    if (current(gen) && activeRequest === req) {
      loading = false;
      emit();
    }
    // Network hiccup/timeout — the fallback timer keeps retrying.
  } finally {
    if (activeRequest === req) {
      activeRequest = null;
      if (dirtyAgain) {
        dirtyAgain = false;
        if (current(gen)) void fetchSnapshot(gen);
      }
    }
  }
}

/** Sequential fallback — only runs while the leader's stream isn't
 *  HELLO-healthy; cancelled the moment a HELLO arrives. Followers never
 *  run it (the leader's catch-up broadcast covers them). */
function scheduleFallback(gen: number) {
  if (fallbackTimer !== null || !leader || sseHealthy) return;
  fallbackTimer = setTimeout(() => {
    fallbackTimer = null;
    if (!current(gen) || !leader || sseHealthy) return;
    void fetchSnapshot(gen).finally(() => {
      if (current(gen) && leader && !sseHealthy) scheduleFallback(gen);
    });
  }, POLL_MS);
}

function cancelFallback() {
  if (fallbackTimer !== null) {
    clearTimeout(fallbackTimer);
    fallbackTimer = null;
  }
}

async function sseLoop(gen: number) {
  while (sseRunning && current(gen) && leader) {
    const epoch = ++transportEpoch;
    const ctrl = new AbortController();
    sseAbort = ctrl;
    sseHealthy = false;
    let helloSeen = false;
    try {
      for await (const n of api.streamNotifications(
        ctrl.signal,
        () => {
          if (!validTransport(gen, epoch) || helloSeen) return;
          helloSeen = true;
          sseHealthy = true;
          cancelFallback();
          void fetchSnapshot(gen);
        },
        () => {
          if (!validTransport(gen, epoch)) return;
          void fetchSnapshot(gen);
        },
      )) {
        if (!validTransport(gen, epoch)) break;
        process(n);
        broadcastNotification(n); // followers get it — no per-tab SSE
        emit();
      }
    } catch {
      // Stream dropped — fallback covers the gap; retry shortly.
    }
    if (!validTransport(gen, epoch)) return; // aborted/demoted/replaced
    sseHealthy = false;
    scheduleFallback(gen);
    // Tracked, cancellable backoff — demotion must not leave a sleeping
    // timer that resurrects a second stream.
    await new Promise<void>((r) => {
      reconnectResolve = r;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        reconnectResolve = null;
        r();
      }, SSE_RECONNECT_MS);
    });
    if (!validTransport(gen, epoch)) return;
    reconnectResolve = null;
    void retryFailedDeliveries();
  }
}

function start() {
  if (running) return;
  running = true;
  const gen = ++generation;
  watchStartedAt = Date.now();
  baselineDone = false;
  loading = true;
  seenIds = new Set();
  startCrossTab();
  leader = isLeader();
  window.addEventListener("focus", onWindowFocus);
  unsubNotif = onNotification((n) => {
    process(n);
    emit();
  });
  unsubInboxChanged = onInboxChanged(() => {
    // Leader catch-up gossiped — followers fetch once, never re-broadcast.
    if (current(gen)) void fetchSnapshot(gen);
  });
  unsubPrefs = onPrefsChanged(() => {
    void loadNotificationPrefs();
  });
  unsubLeader = onLeaderChange((v) => {
    leader = v;
    if (v) {
      startSseFor(gen);
      for (const id of [...deferredReports]) {
        deferredReports.delete(id);
        const n = notifications.find((x) => x.id === id);
        if (!n || n.read) continue;
        seenIds.delete(id);
        process(n, /* reportsOnly */ true);
      }
      void retryFailedDeliveries();
      scheduleFallback(gen);
    } else {
      stopSse(); // epoch bump + abort + cancel — the old loop can't rise
      cancelFallback(); // followers don't poll — the new leader owns it
    }
  });
  void loadNotificationPrefs().then(() => {
    if (!current(gen)) return;
    void fetchSnapshot(gen);
    if (leader) {
      startSseFor(gen);
      scheduleFallback(gen); // runs until the HELLO cancels it
      void retryFailedDeliveries();
    }
  });
}

function startSseFor(gen: number) {
  if (sseRunning) return;
  sseRunning = true;
  void sseLoop(gen);
}

function stopSse() {
  sseRunning = false;
  sseHealthy = false;
  transportEpoch++; // kills every in-flight attempt's callbacks
  cancelReconnect();
  sseAbort?.abort();
  sseAbort = null;
}

function stop() {
  running = false;
  generation++;
  stopSse();
  cancelFallback();
  window.removeEventListener("focus", onWindowFocus);
  activeRequest?.ctrl.abort();
  activeRequest = null;
  livePending = new Set();
  dirtyAgain = false;
  unsubLeader?.();
  unsubLeader = null;
  unsubNotif?.();
  unsubNotif = null;
  unsubPrefs?.();
  unsubPrefs = null;
  unsubInboxChanged?.();
  unsubInboxChanged = null;
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  toasts = [];
  seenIds = new Set();
  deferredReports.clear();
  watchStartedAt = 0;
  baselineDone = false;
  loading = false;
  stopCrossTab();
}

export function dismissToast(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  const timer = timers.get(id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(id);
  }
  emit();
}

function subscribe(cb: Listener): () => void {
  listeners.add(cb);
  refCount++;
  start();
  return () => {
    listeners.delete(cb);
    refCount--;
    if (refCount <= 0) stop();
  };
}

/**
 * Refetch now instead of waiting for the next poll tick — called when the
 * client already knows something happened (e.g. an SSE run-lifecycle
 * event). `delayMs` lets the backend commit first.
 */
export function refreshNotifications(delayMs = 0) {
  if (!running) return;
  broadcastInboxChanged();
  const gen = generation;
  if (delayMs > 0) {
    const t = setTimeout(() => {
      timers.delete("__refresh");
      if (current(gen)) void fetchSnapshot(gen);
    }, delayMs);
    const prev = timers.get("__refresh");
    if (prev) clearTimeout(prev);
    timers.set("__refresh", t);
  } else {
    void fetchSnapshot(gen);
  }
}

export function useNotifications(): Notification[] {
  return useSyncExternalStore(subscribe, () => notifications);
}

export function useNotificationToasts(): Notification[] {
  return useSyncExternalStore(subscribe, () => toasts);
}

/** True until the first inbox snapshot resolves (success or failure) —
 *  shared with the store's refcount, so every consumer sees the same
 *  loading epoch. */
export function useNotificationsLoading(): boolean {
  return useSyncExternalStore(subscribe, () => loading);
}

// A second live instance doubles every timer/socket above — whether from
// Vite re-instantiating this module via a dependency update (dispose can
// be bypassed when the update is accepted upstream) or a duplicate chunk.
// The previous instance's cleanup is stashed globally and run here.
const g = globalThis as { __agentosNotifStoreStop?: () => void };
g.__agentosNotifStoreStop?.();
g.__agentosNotifStoreStop = stop;

// Vite HMR: without disposal every hot-reload leaks the SSE connection,
// poll interval and BroadcastChannel — a few edits to this file exhaust
// the browser's per-origin connection budget and freeze page loads.
if (import.meta.hot) {
  import.meta.hot.dispose(() => stop());
}
