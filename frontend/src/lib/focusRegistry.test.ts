import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./crossTab", () => ({
  peerFocusKeys: vi.fn(() => new Set<string>()),
  selfTabFocused: vi.fn(() => true),
  setLocalFocusKeys: vi.fn(),
}));

import { peerFocusKeys, selfTabFocused } from "./crossTab";
import {
  isSuppressed,
  notificationKeys,
  setFocusedEntities,
} from "./focusRegistry";
import type { Notification } from "./types";

function notif(partial: Partial<Notification>): Notification {
  return {
    id: "n1",
    notification_type: "run_completed",
    severity: "info",
    title: "t",
    message: "m",
    action_path: null,
    entity_id: null,
    entity_type: null,
    agent_id: null,
    agent_name: null,
    event_id: null,
    read: false,
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

afterEach(() => {
  vi.mocked(selfTabFocused).mockReturnValue(true);
  vi.mocked(peerFocusKeys).mockReturnValue(new Set());
  setFocusedEntities([]);
});

describe("notificationKeys", () => {
  it("uses explicit entity_type:entity_id", () => {
    const n = notif({ entity_type: "session", entity_id: "s1" });
    expect(notificationKeys(n)).toContain("session:s1");
  });

  it("derives keys from action_path", () => {
    const n = notif({
      action_path: "/agents/a1/chat?session=s9",
      entity_type: "run",
      entity_id: "r5",
    });
    const keys = notificationKeys(n);
    expect(keys).toContain("run:r5");
    expect(keys).toContain("agent:a1");
    expect(keys).toContain("session:s9");
  });
});

describe("isSuppressed", () => {
  it("exact focused entity in this visible tab suppresses", () => {
    setFocusedEntities(["session:s1", "agent:a1"]);
    const n = notif({ entity_type: "session", entity_id: "s1" });
    expect(isSuppressed(n)).toBe(true);
  });

  it("a run's notification suppresses when its session is focused", () => {
    setFocusedEntities(["session:s9"]);
    const n = notif({
      entity_type: "run",
      entity_id: "r1",
      action_path: "/agents/a1/chat?session=s9",
    });
    expect(isSuppressed(n)).toBe(true);
  });

  it("a different entity does not suppress", () => {
    setFocusedEntities(["session:s1"]);
    const n = notif({ entity_type: "session", entity_id: "other" });
    expect(isSuppressed(n)).toBe(false);
  });

  it("hidden local tab falls back to peer focus", () => {
    vi.mocked(selfTabFocused).mockReturnValue(false);
    setFocusedEntities(["session:s1"]);
    const n = notif({ entity_type: "session", entity_id: "s1" });
    expect(isSuppressed(n)).toBe(false); // local hidden — no suppression
    vi.mocked(peerFocusKeys).mockReturnValue(new Set(["session:s1"]));
    expect(isSuppressed(n)).toBe(true); // visible peer has it focused
  });

  it("visible-but-unfocused window does not suppress (B40)", () => {
    // App window on screen, operator is in another app — the OS ping must
    // still fire; only a *focused* window counts as "already looking".
    vi.mocked(selfTabFocused).mockReturnValue(false);
    setFocusedEntities(["session:s1", "agent:a1"]);
    const n = notif({ entity_type: "session", entity_id: "s1" });
    expect(isSuppressed(n)).toBe(false);
  });

  it("no entity info → never suppressed", () => {
    setFocusedEntities(["session:s1"]);
    expect(isSuppressed(notif({}))).toBe(false);
  });
});
