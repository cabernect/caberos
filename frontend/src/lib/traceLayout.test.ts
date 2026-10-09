import { describe, expect, it } from "vitest";
import type { TimelineEvent } from "./types";
import { buildTraceLayout } from "./traceLayout";

function event(id: string, fields: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    id, type: "tool_call", at: "2026-01-01T00:00:01Z",
    call_id: id, sub_agent_id: null, parent_id: null, status: "complete",
    data: {}, redacted: false, truncated: false, estimated_time: false,
    ...fields,
  };
}

const run = {
  started_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:00:10Z",
};

describe("trace layout", () => {
  it("preserves overlapping spans and exact parents, not chronological guesses", () => {
    const layout = buildTraceLayout([
      event("a", { at: "2026-01-01T00:00:03Z", data: { latency_ms: 2000 } }),
      event("b", { at: "2026-01-01T00:00:04Z", data: { latency_ms: 2500 } }),
      event("child", { parent_id: "a", at: "2026-01-01T00:00:02Z" }),
    ], run);
    const a = layout.byId.get("a")!;
    const b = layout.byId.get("b")!;
    expect(a.leftPercent).toBe(10);
    expect(a.widthPercent).toBe(20);
    expect(b.leftPercent).toBe(15);
    expect(b.widthPercent).toBe(25);
    expect(b.parentId).toBe(layout.rootId);
    expect(layout.byId.get("child")?.depth).toBe(2);
    expect(layout.rows.map((row) => row.id)).toEqual([layout.rootId, "a", "child", "b"]);
    expect(a.timing).toBe("derived");
  });

  it("keeps zero duration distinct from unavailable duration or time", () => {
    const layout = buildTraceLayout([
      event("zero", { data: { latency_ms: 0 } }),
      event("point"),
      event("unknown", { at: null, estimated_time: true, data: { latency_ms: 500 } }),
    ], run);
    expect(layout.byId.get("zero")?.durationMs).toBe(0);
    expect(layout.byId.get("zero")?.widthPercent).toBe(0);
    expect(layout.byId.get("point")?.durationMs).toBeNull();
    expect(layout.byId.get("point")?.timing).toBe("point");
    expect(layout.byId.get("unknown")?.leftPercent).toBeNull();
    expect(layout.byId.get("unknown")?.durationMs).toBe(500);
  });

  it("labels coarse receipt placement as derived and keeps recorded latency", () => {
    const layout = buildTraceLayout([
      event("model", {
        type: "model_call", at: "2026-10-06T02:40:59Z",
        data: { latency_ms: 6357 },
      }),
    ], {
      started_at: "2026-10-06T02:40:53.239126Z",
      completed_at: "2026-10-06T02:40:59.686170Z",
    });
    const model = layout.byId.get("model")!;
    expect(model.startMs).toBe(layout.originMs);
    expect(model.durationMs).toBe(6357);
    expect(model.adjusted).toBe(true);
    expect(model.timing).toBe("derived");
    expect(model.endMs! - model.startMs!).toBe(6357);
  });

  it("breaks cycles and leaves missing parent references at run scope", () => {
    const layout = buildTraceLayout([
      event("a", { parent_id: "b" }),
      event("b", { parent_id: "a" }),
      event("orphan", { parent_id: "missing" }),
    ], run);
    expect(layout.rows).toHaveLength(4);
    expect(layout.rows.filter((row) => row.event).every((row) => row.depth === 1)).toBe(true);
  });

  it("does not fabricate a completion for an active run or invalid durations", () => {
    const layout = buildTraceLayout([
      event("bad", { data: { latency_ms: -1 } }),
      event("invalid", { at: "not a date" }),
    ], { ...run, completed_at: null });
    expect(layout.byId.get(layout.rootId)?.endMs).toBeNull();
    expect(layout.byId.get(layout.rootId)?.durationMs).toBeNull();
    expect(layout.byId.get("bad")?.durationMs).toBeNull();
    expect(layout.byId.get("invalid")?.timing).toBe("unknown");
  });
});
