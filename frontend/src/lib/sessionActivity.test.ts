import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: { streamSessionActivity: vi.fn() },
}));

import {
  handleSessionActivityEvent,
  onSessionActivity,
  primeLearning,
  stopSessionActivity,
  useLearningSessions,
} from "./sessionActivity";
import type { SessionActivityEvent } from "./types";

const ev = (session_id: string, phase: SessionActivityEvent["phase"]) =>
  ({
    type: "session_activity",
    kind: "session_close",
    phase,
    session_id,
    agent_id: "a1",
  }) as SessionActivityEvent;

afterEach(() => {
  // Shared module state — reset between tests.
  stopSessionActivity();
  primeLearning([]);
});

describe("sessionActivity", () => {
  it("started adds, finished/failed remove the learning indicator", () => {
    const { result } = renderHook(() => useLearningSessions());
    act(() => handleSessionActivityEvent(ev("s1", "started")));
    expect(result.current.has("s1")).toBe(true);
    act(() => handleSessionActivityEvent(ev("s1", "finished")));
    expect(result.current.has("s1")).toBe(false);
    act(() => handleSessionActivityEvent(ev("s2", "started")));
    act(() => handleSessionActivityEvent(ev("s2", "failed")));
    expect(result.current.size).toBe(0);
  });

  it("primes from the sessions list and unions with live events", () => {
    const { result } = renderHook(() => useLearningSessions());
    act(() => primeLearning(["s-a", "s-b"]));
    expect([...result.current].sort()).toEqual(["s-a", "s-b"]);
    // A live 'started' arriving mid-fetch survives the next snapshot.
    act(() => handleSessionActivityEvent(ev("s-live", "started")));
    act(() => primeLearning(["s-a"]));
    expect(result.current.has("s-live")).toBe(true);
    // Stale snapshot entries clear on the next authoritative fetch.
    expect(result.current.has("s-b")).toBe(false);
  });

  it("notifies raw-event subscribers for UI refresh", () => {
    const seen: string[] = [];
    const off = onSessionActivity((e) => seen.push(e.phase));
    handleSessionActivityEvent(ev("s1", "started"));
    handleSessionActivityEvent(ev("s1", "finished"));
    off();
    handleSessionActivityEvent(ev("s1", "started"));
    expect(seen).toEqual(["started", "finished"]);
  });
});
