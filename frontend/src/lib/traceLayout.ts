import type { RunDetail, TimelineEvent } from "./types";

export type TraceTiming = "observed" | "derived" | "point" | "unknown";

export interface TraceRow {
  id: string;
  event: TimelineEvent | null;
  parentId: string | null;
  depth: number;
  children: string[];
  startMs: number | null;
  endMs: number | null;
  durationMs: number | null;
  timing: TraceTiming;
  adjusted: boolean;
  leftPercent: number | null;
  widthPercent: number | null;
}

type RunTiming = Pick<RunDetail, "started_at" | "completed_at">;

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function duration(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

export function buildTraceLayout(events: TimelineEvent[], run?: RunTiming) {
  let rootId = "trace-root";
  while (events.some((event) => event.id === rootId)) rootId = `_${rootId}`;
  const start = timestamp(run?.started_at)
    ?? timestamp(events.find((event) => event.type === "run_started")?.at);
  const recordedEnd = timestamp(run?.completed_at)
    ?? timestamp(events.find((event) => event.type === "run_completed")?.at);
  const end = start !== null && recordedEnd !== null && recordedEnd >= start
    ? recordedEnd
    : null;
  const root: TraceRow = {
    id: rootId,
    event: null,
    parentId: null,
    depth: 0,
    children: [],
    startMs: start,
    endMs: end,
    durationMs: start !== null && end !== null ? end - start : null,
    timing: start !== null ? "observed" : "unknown",
    adjusted: false,
    leftPercent: null,
    widthPercent: null,
  };
  const byId = new Map<string, TraceRow>([[rootId, root]]);

  for (const event of events) {
    const at = timestamp(event.at);
    const measuredDuration = duration(event.data.latency_ms);
    let spanStart = at;
    let spanEnd = at;
    let adjusted = false;
    let timing: TraceTiming = at === null ? "unknown" : "point";
    if (at !== null && measuredDuration !== null) {
      // created_at is a receipt timestamp, not an instrumented span boundary.
      // Old SQLite rows are second-resolution: keep measured duration intact,
      // but mark placement as derived when clamping to the recorded run start.
      spanStart = at - measuredDuration;
      if (start !== null && spanStart < start) {
        spanStart = start;
        adjusted = true;
      }
      spanEnd = spanStart + measuredDuration;
      timing = "derived";
    }
    byId.set(event.id, {
      id: event.id,
      event,
      parentId: rootId,
      depth: 1,
      children: [],
      startMs: spanStart,
      endMs: spanEnd,
      durationMs: measuredDuration,
      timing,
      adjusted,
      leftPercent: null,
      widthPercent: null,
    });
  }

  // Only explicit backend parent IDs establish ancestry. Never infer causality
  // from neighboring timestamps, turn numbers, or a capability's name.
  for (const event of events) {
    const row = byId.get(event.id)!;
    const parent = event.parent_id;
    if (!parent || parent === row.id || !byId.has(parent)) continue;
    const seen = new Set([row.id]);
    let cursor: string | null = parent;
    let cyclic = false;
    while (cursor && cursor !== rootId) {
      if (seen.has(cursor)) {
        cyclic = true;
        break;
      }
      seen.add(cursor);
      cursor = byId.get(cursor)?.event?.parent_id ?? null;
    }
    if (!cyclic) row.parentId = parent;
  }
  for (const row of byId.values()) {
    if (row.parentId) byId.get(row.parentId)!.children.push(row.id);
  }
  const rows: TraceRow[] = [];
  function visit(id: string, depth: number) {
    const row = byId.get(id)!;
    row.depth = depth;
    rows.push(row);
    for (const child of row.children) visit(child, depth + 1);
  }
  visit(rootId, 0);

  const knownStarts = rows.flatMap((row) => row.startMs === null ? [] : [row.startMs]);
  const originMs = start ?? (knownStarts.length ? Math.min(...knownStarts) : null);
  const knownEnds = rows.flatMap((row) => row.endMs === null ? [] : [row.endMs]);
  const extentMs = originMs !== null && knownEnds.length
    ? Math.max(originMs, ...knownEnds) - originMs
    : 0;
  for (const row of rows) {
    if (originMs === null || row.startMs === null) continue;
    const visualExtent = extentMs || 1;
    row.leftPercent = Math.max(0, Math.min(100,
      (row.startMs - originMs) / visualExtent * 100));
    row.widthPercent = row.endMs !== null
      ? Math.max(0, Math.min(100 - row.leftPercent,
        (row.endMs - row.startMs) / visualExtent * 100))
      : null;
  }
  return { rootId, rows, byId, originMs, extentMs };
}
