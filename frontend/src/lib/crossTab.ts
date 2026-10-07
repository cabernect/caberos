/**
 * Cross-tab coordination for notifications (W9).
 *
 * Every open tab joins a BroadcastChannel. Leadership is deterministic —
 * the lexicographically smallest live tab id leads — so every tab computes
 * the same leader without a negotiation round. The leader owns OS-surface
 * delivery (browser/system notifications) and all delivery reporting;
 * followers render their own toasts only.
 *
 * Focus gossip rides on heartbeats: each tab publishes the entity keys it
 * is currently showing (e.g. `session:abc`) plus its visibility. A
 * notification whose entity is focused in ANY visible tab is suppressed
 * everywhere.
 */

import type { Notification } from "./types";

type PeerState = {
  visible: boolean;
  focused: boolean;
  keys: string[];
  lastSeen: number;
};

type TabMsg =
  | { type: "hello"; tabId: string; visible: boolean; focused?: boolean; keys: string[] }
  | { type: "heartbeat"; tabId: string; visible: boolean; focused?: boolean; keys: string[] }
  | { type: "notification"; tabId: string; notification: Notification }
  | { type: "prefs"; tabId: string }
  | { type: "bye"; tabId: string };

const CHANNEL_NAME = "agentos-notifs";
const HEARTBEAT_MS = 2_000;
const STALE_MS = 6_000;

export const TAB_ID =
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `tab-${Math.random().toString(36).slice(2)}`;

const peers = new Map<string, PeerState>();
const leaderListeners = new Set<(leader: boolean) => void>();
const notificationListeners = new Set<(n: Notification) => void>();
const prefsListeners = new Set<() => void>();

let channel: BroadcastChannel | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let localKeys: string[] = [];
let wasLeader = false;
let running = false;

function selfVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** "Looking at it" = tab visible AND its window focused. A backgrounded
 *  window (user in another app) still reports visible, but the operator
 *  isn't watching — OS pings exist for exactly that case (B40). */
function selfFocused(): boolean {
  return selfVisible() && (typeof document === "undefined" || document.hasFocus());
}

function pruneStale() {
  const now = Date.now();
  let changed = false;
  for (const [id, p] of peers) {
    if (now - p.lastSeen > STALE_MS) {
      peers.delete(id);
      changed = true;
    }
  }
  return changed;
}

function computeLeader(): boolean {
  pruneStale();
  let min = TAB_ID;
  for (const id of peers.keys()) if (id < min) min = id;
  return min === TAB_ID;
}

function maybeNotifyLeader() {
  const leader = computeLeader();
  if (leader !== wasLeader) {
    wasLeader = leader;
    for (const cb of leaderListeners) cb(leader);
  }
}

function post(msg: TabMsg) {
  try {
    channel?.postMessage(msg);
  } catch {
    // Channel closed mid-shutdown — harmless.
  }
}

function beat() {
  post({
    type: "heartbeat",
    tabId: TAB_ID,
    visible: selfVisible(),
    focused: selfFocused(),
    keys: localKeys,
  });
  maybeNotifyLeader();
}

function handle(msg: TabMsg) {
  if (!msg || msg.tabId === TAB_ID) return;
  if (msg.type === "notification") {
    for (const cb of notificationListeners) cb(msg.notification);
    return;
  }
  if (msg.type === "prefs") {
    for (const cb of prefsListeners) cb();
    return;
  }
  if (msg.type === "bye") {
    peers.delete(msg.tabId);
    maybeNotifyLeader();
    return;
  }
  peers.set(msg.tabId, {
    visible: msg.visible,
    // Pre-B40 peers don't send `focused` — fall back to visible.
    focused: msg.focused ?? msg.visible,
    keys: msg.keys,
    lastSeen: Date.now(),
  });
  if (msg.type === "hello") {
    // New tab joined — answer immediately so it learns the peer set fast.
    beat();
    return;
  }
  maybeNotifyLeader();
}

function onVisibility() {
  // Visibility affects both leadership relevance and focus suppression —
  // publish the change now rather than waiting for the next heartbeat.
  beat();
}

function onFocusChange() {
  // Window focus gates entity suppression (B40) — gossip it immediately.
  beat();
}

function onUnload() {
  post({ type: "bye", tabId: TAB_ID });
}

export function startCrossTab() {
  if (running || typeof BroadcastChannel === "undefined") {
    // No BroadcastChannel (tests, very old engines): this tab leads itself.
    if (!running) {
      running = true;
      wasLeader = true;
      for (const cb of leaderListeners) cb(true);
    }
    return;
  }
  running = true;
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.onmessage = (e) => handle(e.data as TabMsg);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("focus", onFocusChange);
  window.addEventListener("blur", onFocusChange);
  window.addEventListener("beforeunload", onUnload);
  wasLeader = computeLeader(); // alone until peers answer
  heartbeatTimer = setInterval(beat, HEARTBEAT_MS);
  post({
    type: "hello",
    tabId: TAB_ID,
    visible: selfVisible(),
    focused: selfFocused(),
    keys: localKeys,
  });
  if (wasLeader) for (const cb of leaderListeners) cb(true);
}

export function stopCrossTab() {
  running = false;
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
  document.removeEventListener("visibilitychange", onVisibility);
  window.removeEventListener("focus", onFocusChange);
  window.removeEventListener("blur", onFocusChange);
  window.removeEventListener("beforeunload", onUnload);
  onUnload();
  channel?.close();
  channel = null;
  peers.clear();
}

/** Publish which entity keys this tab is currently focused on. */
export function setLocalFocusKeys(keys: string[]) {
  localKeys = keys;
  beat();
}

/** Entity keys in a peer tab that is visible AND window-focused — an
 *  unfocused window means the operator isn't actually looking (B40). */
export function peerFocusKeys(): Set<string> {
  pruneStale();
  const out = new Set<string>();
  for (const p of peers.values()) {
    if (p.visible && p.focused) for (const k of p.keys) out.add(k);
  }
  return out;
}

/** Any visible peer tab — used to decide whether a toast showed anywhere. */
export function anyPeerVisible(): boolean {
  pruneStale();
  for (const p of peers.values()) if (p.visible) return true;
  return false;
}

export function isLeader(): boolean {
  if (!running || channel === null) return true; // solo mode
  return computeLeader();
}

export function onLeaderChange(cb: (leader: boolean) => void): () => void {
  leaderListeners.add(cb);
  return () => leaderListeners.delete(cb);
}

/** Leader → followers: the leader gossips each SSE event so follower
 *  tabs never need their own stream connection. */
export function broadcastNotification(n: Notification) {
  post({ type: "notification", tabId: TAB_ID, notification: n });
}

export function onNotification(cb: (n: Notification) => void): () => void {
  notificationListeners.add(cb);
  return () => notificationListeners.delete(cb);
}

/** A tab that persisted a prefs change gossips it so every other tab
 *  re-fetches — the leader's suppression matrix must not go stale while
 *  it still holds the ping authority (quiet hours muted nothing until a
 *  follower happened to reload — B36). */
export function broadcastPrefsChanged() {
  post({ type: "prefs", tabId: TAB_ID });
}

export function onPrefsChanged(cb: () => void): () => void {
  prefsListeners.add(cb);
  return () => prefsListeners.delete(cb);
}

export function selfTabVisible(): boolean {
  return selfVisible();
}

export function selfTabFocused(): boolean {
  return selfFocused();
}

// Same singleton rule as notificationStore — a re-instantiated module
// would double the heartbeat and keep a ghost channel alive, so peers
// would elect a dead leader (B37).
const g = globalThis as { __agentosCrossTabStop?: () => void };
g.__agentosCrossTabStop?.();
g.__agentosCrossTabStop = stopCrossTab;

// Vite HMR: a disposed module must drop its heartbeat + channel, or the
// zombie keeps a dead tab "alive" — peers then elect the ghost leader.
if (import.meta.hot) {
  import.meta.hot.dispose(() => stopCrossTab());
}
