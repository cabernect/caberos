/**
 * Focused-entity registry (W9).
 *
 * Pages declare which entities the operator is currently looking at —
 * `{kind}:{id}` keys like `session:abc`, `agent:xyz`, `schedule:s1`.
 * A notification is suppressed when one of its entity keys is focused in
 * a *focused* tab (this one or a peer — see crossTab). Visible-but-unfocused
 * windows don't count: the operator isn't actually watching (B40).
 * Suppression kills attention surfaces only; the inbox row is still written
 * and auto-read.
 */

import type { Notification } from "./types";
import { peerFocusKeys, selfTabFocused, setLocalFocusKeys } from "./crossTab";

let localKeys = new Set<string>();

/** Replace this tab's focused-entity set. Pages call this on mount/change
 *  and with `[]` on unmount. */
export function setFocusedEntities(keys: string[] | null) {
  localKeys = new Set(keys ?? []);
  setLocalFocusKeys([...localKeys]);
}

export function getFocusedEntities(): string[] {
  return [...localKeys];
}

/**
 * Entity keys a notification refers to. Derived from its explicit
 * entity_type/entity_id plus whatever its deep link points at — so a
 * `run_failed` (entity=run) still suppresses while the operator stares at
 * the session that run belongs to.
 */
export function notificationKeys(n: Notification): string[] {
  const keys: string[] = [];
  if (n.entity_type && n.entity_id) keys.push(`${n.entity_type}:${n.entity_id}`);
  const path = n.action_path;
  if (path) {
    const agent = path.match(/\/agents\/([^/?#]+)/);
    if (agent) keys.push(`agent:${agent[1]}`);
    const session = path.match(/[?&]session=([^&#]+)/);
    if (session) keys.push(`session:${session[1]}`);
    const focus = path.match(/[?&]focus=([^&#]+)/);
    if (focus) keys.push(`focus:${focus[1]}`);
    const skill = path.match(/\/skills\/([^/?#]+)/);
    if (skill) keys.push(`skill:${skill[1]}`);
  }
  return keys;
}

/** True when the operator is already looking at this notification's
 *  subject — exact entity focused in a visible AND focused tab (local
 *  or peer). An unfocused window doesn't suppress: OS pings are for when
 *  you're not looking (B40). */
export function isSuppressed(n: Notification): boolean {
  const keys = notificationKeys(n);
  if (keys.length === 0) return false;
  if (selfTabFocused() && keys.some((k) => localKeys.has(k))) return true;
  const peers = peerFocusKeys();
  return keys.some((k) => peers.has(k));
}
