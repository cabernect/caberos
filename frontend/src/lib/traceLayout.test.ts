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

  it("collects post-run ledgered work under a synthetic section row", () => {
    const layout = buildTraceLayout([
      event("gen", { type: "model_call", at: "2026-01-01T00:00:05Z", data: { latency_ms: 3310 } }),
      event("notif", { type: "notification", at: "2026-01-01T00:00:09Z" }),
      event("del1", { type: "notification_delivery", at: "2026-01-01T00:00:12Z", parent_id: "notif" }),
      event("del2", { type: "notification_delivery", at: "2026-01-01T00:00:13Z", parent_id: "notif" }),
      event("auxgen", { type: "model_call", at: "2026-01-01T00:00:30Z", data: { latency_ms: 4700 } }),
    ], run);
    const section = layout.rows.find((row) => row.postRun);
    expect(section).toBeDefined();
    expect(section!.parentId).toBe(layout.rootId);
    // deliveries keep their true event parent but display under the section
    expect(section!.children).toEqual(["del1", "del2", "auxgen"]);
    expect(layout.byId.get("del1")?.parentId).toBe(section!.id);
    expect(layout.byId.get("del1")?.event?.parent_id).toBe("notif");
    expect(layout.byId.get("notif")?.children).toEqual([]);
    expect(section!.postRunCount).toBe(3);
    // in-run work renders before the section; nothing outside the section follows it
    expect(layout.rows.map((row) => row.id)).toEqual([
      layout.rootId, "gen", "notif", section!.id, "del1", "del2", "auxgen",
    ]);
  });

  it("keeps a fully-post-run subtree nested under the section", () => {
    const layout = buildTraceLayout([
      event("env", { type: "notification", at: "2026-01-01T00:00:20Z" }),
      event("c1", { type: "notification_delivery", at: "2026-01-01T00:00:21Z", parent_id: "env" }),
      event("c2", { type: "notification_delivery", at: "2026-01-01T00:00:22Z", parent_id: "env" }),
    ], run);
    const section = layout.rows.find((row) => row.postRun)!;
    expect(section.children).toEqual(["env"]);
    expect(layout.byId.get("env")?.children).toEqual(["c1", "c2"]);
    expect(section.postRunCount).toBe(3);
  });

  it("adds no section when nothing was ledgered outside the window", () => {
    const layout = buildTraceLayout([
      event("gen", { type: "model_call", at: "2026-01-01T00:00:05Z", data: { latency_ms: 1000 } }),
      event("notif", { type: "notification", at: "2026-01-01T00:00:10.4Z" }),
    ], run);
    expect(layout.rows.some((row) => row.postRun)).toBe(false);
    expect(layout.byId.get("notif")?.outsideWindow).toBeUndefined();
  });

  it("adds no section while the run window is still open", () => {
    const layout = buildTraceLayout([
      event("gen", { type: "model_call", at: "2026-01-01T00:00:30Z", data: { latency_ms: 4000 } }),
    ], { ...run, completed_at: null });
    expect(layout.rows.some((row) => row.postRun)).toBe(false);
    expect(layout.byId.get("gen")?.outsideWindow).toBeUndefined();
  });
});
