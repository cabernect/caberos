import { useSyncExternalStore } from "react";
import { api } from "./api";
import type { Notification } from "./types";

/**
 * App-level notification store.
 *
 * One poller feeds both the bell badge (NotificationCenter) and the toast
 * layer (NotificationToasts). The first fetch establishes the baseline —
 * existing notifications don't toast; only newly-arrived unread ones do.
 */

const POLL_MS = 15_000;
const TOAST_DURATION_MS = 6_000;

type Listener = () => void;

let notifications: Notification[] = [];
let toasts: Notification[] = [];
const listeners = new Set<Listener>();
let seenIds: Set<string> | null = null;
let intervalId: ReturnType<typeof setInterval> | null = null;
let refCount = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

function emit() {
  for (const cb of listeners) cb();
}

async function poll() {
  try {
    const list = await api.listNotifications();
    notifications = list;
    if (seenIds === null) {
      seenIds = new Set(list.map((n) => n.id));
    } else {
      const fresh = list.filter((n) => !n.read && !seenIds!.has(n.id));
      for (const n of fresh) seenIds!.add(n.id);
      if (fresh.length > 0) {
        toasts = [...toasts, ...fresh];
        for (const n of fresh) {
          timers.set(
            n.id,
            setTimeout(() => dismissToast(n.id), TOAST_DURATION_MS),
          );
        }
      }
    }
    emit();
  } catch {
    // Network hiccup — keep polling.
  }
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
  if (intervalId === null) {
    void poll();
    intervalId = setInterval(poll, POLL_MS);
  }
  return () => {
    listeners.delete(cb);
    refCount--;
    if (refCount <= 0 && intervalId !== null) {
      clearInterval(intervalId);
      intervalId = null;
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
      toasts = [];
      seenIds = null;
    }
  };
}

export function useNotifications(): Notification[] {
  return useSyncExternalStore(subscribe, () => notifications);
}

export function useNotificationToasts(): Notification[] {
  return useSyncExternalStore(subscribe, () => toasts);
}
