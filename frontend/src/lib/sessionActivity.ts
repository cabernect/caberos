/**
 * Session-activity store — tracks which sessions are being closed/summarized
 * right now, per tab. Fed by GET /api/chat/{agent}/session-activity/stream
 * (live events) plus the `learning` flag primed from sessions-list fetches.
 *
 * Two sources are kept separate and unioned: `liveIds` is event-driven
 * (started adds, finished/failed removes), `snapshotIds` is replaced by each
 * list fetch. Events are transient — a missed frame can't wedge the
 * indicator because the next list fetch resets the snapshot half.
 */

import { useSyncExternalStore } from "react";
import { api } from "./api";
import type { SessionActivityEvent } from "./types";

let liveIds = new Set<string>();
let snapshotIds = new Set<string>();
let learningIds = new Set<string>();

const listeners = new Set<() => void>();
const activityListeners = new Set<(ev: SessionActivityEvent) => void>();

let currentAgentId: string | null = null;
let running = false;
let abort: AbortController | null = null;
const RECONNECT_MS = 3_000;

function emit() {
  for (const l of listeners) l();
}

function recompute() {
  const next = new Set([...liveIds, ...snapshotIds]);
  if (next.size === learningIds.size && [...next].every((id) => learningIds.has(id))) {
    return;
  }
  learningIds = next;
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useLearningSessions(): Set<string> {
  return useSyncExternalStore(subscribe, () => learningIds);
}

/** Raw event subscription — e.g. to refresh the session list on activity. */
export function onSessionActivity(cb: (ev: SessionActivityEvent) => void) {
  activityListeners.add(cb);
  return () => {
    activityListeners.delete(cb);
  };
}

/** Replace the snapshot half with the authoritative flags from a list fetch. */
export function primeLearning(ids: string[]) {
  snapshotIds = new Set(ids);
  recompute();
}

export function handleSessionActivityEvent(ev: SessionActivityEvent) {
  const next = new Set(liveIds);
  if (ev.phase === "started") next.add(ev.session_id);
  else next.delete(ev.session_id); // finished | failed both end the attempt
  liveIds = next;
  recompute();
  for (const cb of activityListeners) cb(ev);
}

export function startSessionActivity(agentId: string) {
  if (running && currentAgentId === agentId) return;
  stopSessionActivity();
  currentAgentId = agentId;
  running = true;
  void loop(agentId);
}

export function stopSessionActivity() {
  running = false;
  currentAgentId = null;
  abort?.abort();
  abort = null;
  if (liveIds.size || snapshotIds.size) {
    liveIds = new Set();
    snapshotIds = new Set();
    recompute();
  }
}

async function loop(agentId: string) {
  while (running && currentAgentId === agentId) {
    const ctrl = new AbortController();
    abort = ctrl;
    try {
      for await (const ev of api.streamSessionActivity(agentId, ctrl.signal)) {
        if (!running || currentAgentId !== agentId) break;
        handleSessionActivityEvent(ev);
      }
    } catch {
      // Stream dropped — fall through to a bounded reconnect.
    }
    if (!running || currentAgentId !== agentId) return;
    await new Promise((r) => setTimeout(r, RECONNECT_MS));
  }
}
