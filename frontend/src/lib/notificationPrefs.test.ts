import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  api: {
    getNotificationPrefs: vi.fn(),
    putNotificationPrefs: vi.fn(),
  },
}));

import { api } from "./api";
import {
  getNotificationPrefs,
  inQuietHours,
  loadNotificationPrefs,
  surfaceEnabled,
  saveNotificationPrefs,
} from "./notificationPrefs";
import type { NotificationPrefs } from "./types";

const PREFS: NotificationPrefs = {
  defaults: { inbox: true, toast: true, browser: false, system: false },
  overrides: { run_failed: { toast: false, browser: true } },
  quiet_hours: { enabled: false, start: "22:00", end: "07:00", tz: null },
  permissions: { browser_asked: false, tauri_asked: false },
};

beforeEach(async () => {
  vi.mocked(api.getNotificationPrefs).mockResolvedValue(PREFS);
  await loadNotificationPrefs();
});

describe("surfaceEnabled", () => {
  it("resolves defaults when no override exists", () => {
    expect(surfaceEnabled("run_completed", "toast")).toBe(true);
    expect(surfaceEnabled("run_completed", "browser")).toBe(false);
  });

  it("override wins over default", () => {
    expect(surfaceEnabled("run_failed", "toast")).toBe(false);
    expect(surfaceEnabled("run_failed", "browser")).toBe(true);
  });

  it("partial override falls back to defaults for other surfaces", () => {
    expect(surfaceEnabled("run_failed", "inbox")).toBe(true);
  });
});

describe("saveNotificationPrefs overrides", () => {
  it("null deletes an override — the patch is sent, not the blob", async () => {
    // B35: clients PUT only the fields they mean to change; a null
    // override is the explicit delete (omission can't express it).
    vi.mocked(api.putNotificationPrefs).mockImplementation(async () => ({
      ...PREFS,
      overrides: {},
    }));
    await saveNotificationPrefs({ overrides: { run_failed: null } });
    expect(api.putNotificationPrefs).toHaveBeenCalledWith({
      overrides: { run_failed: null },
    });
    expect(getNotificationPrefs().overrides).toEqual({});
    expect(surfaceEnabled("run_failed", "toast")).toBe(true);
  });

  it("setting an override merges per event type", async () => {
    // Server merges onto the stored blob — returns both keys.
    vi.mocked(api.putNotificationPrefs).mockResolvedValue({
      ...PREFS,
      overrides: { ...PREFS.overrides, run_completed: { toast: false } },
    });
    await saveNotificationPrefs({
      overrides: { run_completed: { toast: false } },
    });
    // New key added; the pre-existing run_failed override is untouched.
    expect(surfaceEnabled("run_completed", "toast")).toBe(false);
    expect(surfaceEnabled("run_completed", "inbox")).toBe(true);
    expect(surfaceEnabled("run_failed", "toast")).toBe(false);
  });
});

describe("inQuietHours", () => {
  const at = (h: number, m = 0) => new Date(2026, 0, 15, h, m);

  it("disabled → never quiet", () => {
    expect(inQuietHours(at(23))).toBe(false);
  });

  it("overnight window wraps midnight", async () => {
    vi.mocked(api.putNotificationPrefs).mockResolvedValue({
      ...PREFS,
      quiet_hours: { enabled: true, start: "22:00", end: "07:00", tz: null },
    });
    await saveNotificationPrefs({
      quiet_hours: { enabled: true, start: "22:00", end: "07:00", tz: null },
    });
    expect(inQuietHours(at(23, 30))).toBe(true);
    expect(inQuietHours(at(3))).toBe(true);
    expect(inQuietHours(at(12))).toBe(false);
    expect(inQuietHours(at(7))).toBe(false); // end exclusive
  });

  it("same-day window", async () => {
    vi.mocked(api.putNotificationPrefs).mockResolvedValue({
      ...PREFS,
      quiet_hours: { enabled: true, start: "12:00", end: "14:00", tz: null },
    });
    await saveNotificationPrefs({
      quiet_hours: { enabled: true, start: "12:00", end: "14:00", tz: null },
    });
    expect(inQuietHours(at(13))).toBe(true);
    expect(inQuietHours(at(15))).toBe(false);
  });
});
