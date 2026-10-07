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
  broadcastNotification,
  isLeader,
  onLeaderChange,
  onNotification,
  onPrefsChanged,
  selfTabVisible,
  startCrossTab,
  stopCrossTab,
} from "./crossTab";
import { isSuppressed } from "./focusRegistry";
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
let intervalId: ReturnType<typeof setInterval> | null = null;
let refCount = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

let sseAbort: AbortController | null = null;
let sseRunning = false;
let leader = false;
// Unread items this tab processed as a follower — a follower can't report
// deliveries, so seenIds alone would suppress the leader-side pass forever
// if the tab is later promoted (B38). On promotion each deferred id is
// re-processed for reporting only.
const deferredReports = new Set<string>();
let unsubLeader: (() => void) | null = null;
let unsubNotif: (() => void) | null = null;
let unsubPrefs: (() => void) | null = null;

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

function report(n: Notification, adapter: string, state: string, error?: string) {
  api.reportDelivery(n.id, adapter, state, error).catch(() => {});
}

function markRead(n: Notification) {
  api.markNotificationRead(n.id).catch(() => {});
  deferredReports.delete(n.id); // read rows never need pings or reports
  const row = notifications.find((x) => x.id === n.id);
  if (row) row.read = true;
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
  report(n, "toast", selfTabVisible() || anyPeerVisible() ? "delivered" : "suppressed");
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

  if (!n.read && toastWanted && !focused && !quiet && selfTabVisible() && !reportsOnly) {
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

// Serialize the poll: setInterval fires regardless of the previous tick,
// so an unbounded fetch stacks one socket per 5 s until the per-origin
// connection pool is gone (ERR_INSUFFICIENT_RESOURCES on every request,
// page loads freeze — B37). The fetch is also bounded — a hung request
// would hold its slot forever.
let pollInFlight = false;
async function poll() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const list = await api.listNotifications(false, AbortSignal.timeout(15_000));
    if (!baselineDone) {
      // First fetch is the baseline — existing rows don't re-deliver.
      for (const n of list) seenIds.add(n.id);
      baselineDone = true;
      notifications = list;
    } else {
      notifications = list;
      for (const n of list) {
        if (!n.read && !seenIds.has(n.id)) process(n); // SSE-gap fallback
      }
    }
    emit();
  } catch {
    // Network hiccup/timeout — keep polling.
  } finally {
    pollInFlight = false;
  }
}

async function sseLoop() {
  while (sseRunning) {
    try {
      sseAbort = new AbortController();
      for await (const n of api.streamNotifications(sseAbort.signal)) {
        if (!sseRunning) break;
        process(n);
        broadcastNotification(n); // followers get it via channel — no per-tab SSE
        emit();
      }
    } catch {
      // Stream dropped — poll covers the gap; retry shortly.
    }
    if (sseRunning) {
      await new Promise((r) => setTimeout(r, SSE_RECONNECT_MS));
      void retryFailedDeliveries();
    }
  }
}

/** Only the leader holds the SSE socket — every open tab holding its own
 *  stream exhausts the browser's 6-connections-per-origin budget fast
 *  (SSE + run streams + HMR socket add up), freezing all page loads. */
function startSse() {
  if (sseRunning) return;
  sseRunning = true;
  void sseLoop();
}

function stopSse() {
  sseRunning = false;
  sseAbort?.abort();
  sseAbort = null;
}

function start() {
  if (intervalId !== null) return;
  baselineDone = false;
  seenIds = new Set();
  startCrossTab();
  leader = isLeader();
  unsubNotif = onNotification((n) => {
    process(n);
    emit();
  });
  // A peer tab that saved prefs broadcasts a nudge — re-fetch so this
  // tab's suppression matrix (quiet hours, overrides) matches (B36).
  unsubPrefs = onPrefsChanged(() => {
    void loadNotificationPrefs();
  });
  unsubLeader = onLeaderChange((v) => {
    leader = v;
    if (v) {
      startSse();
      // Items poll-seen while this tab was a follower never got delivery
      // reports (seenIds suppressed re-processing — B38). Replay the
      // leader-side pass for anything still unread; toasts aren't re-shown
      // here because this tab already rendered them.
      for (const id of [...deferredReports]) {
        deferredReports.delete(id);
        const n = notifications.find((x) => x.id === id);
        if (!n || n.read) continue;
        seenIds.delete(id);
        process(n, /* reportsOnly */ true);
      }
      void retryFailedDeliveries(); // new leader picks up the backlog
    } else {
      stopSse(); // hand the socket to the new leader
    }
  });
  void loadNotificationPrefs().then(() => {
    void poll();
    intervalId = setInterval(poll, POLL_MS);
    if (leader) startSse();
    void retryFailedDeliveries();
  });
}

function stop() {
  stopSse();
  unsubLeader?.();
  unsubLeader = null;
  unsubNotif?.();
  unsubNotif = null;
  unsubPrefs?.();
  unsubPrefs = null;
  if (intervalId !== null) clearInterval(intervalId);
  intervalId = null;
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  toasts = [];
  seenIds = new Set();
  deferredReports.clear();
  baselineDone = false;
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
  if (delayMs > 0) {
    setTimeout(() => void poll(), delayMs);
  } else {
    void poll();
  }
}

export function useNotifications(): Notification[] {
  return useSyncExternalStore(subscribe, () => notifications);
}

export function useNotificationToasts(): Notification[] {
  return useSyncExternalStore(subscribe, () => toasts);
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
