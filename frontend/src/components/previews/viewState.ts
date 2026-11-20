/**
 * Per-source view-state store — slide position, zoom, sheet selection.
 * Keyed by the preview payload's source identity (sha256 of the exact
 * bytes rendered), so state follows content: a new revision or an
 * external edit gets fresh state, while revisiting the same bytes
 * restores where the operator left off. Bounded FIFO — oldest key
 * evicted first; losing state is cosmetic, never data.
 */

const store = new Map<string, Map<string, unknown>>();
const MAX_KEYS = 64;

export function readView<T>(key: string, field: string, fallback: T): T {
  const fields = store.get(key);
  const value = fields?.get(field);
  return value === undefined ? fallback : (value as T);
}

export function writeView(key: string, field: string, value: unknown): void {
  let fields = store.get(key);
  if (!fields) {
    if (store.size >= MAX_KEYS) {
      const oldest = store.keys().next().value;
      if (oldest !== undefined) store.delete(oldest);
    }
    fields = new Map();
    store.set(key, fields);
  }
  fields.set(field, value);
}

/** Identity for view state — exact rendered bytes when declared,
 *  else a stable kind+path fallback for payloads without source info. */
export function viewStateKey(payload: {
  kind: string;
  path?: string;
  name?: string;
  source?: { sha256?: string };
}): string {
  return payload.source?.sha256 ?? `${payload.kind}:${payload.path ?? payload.name ?? ""}`;
}
