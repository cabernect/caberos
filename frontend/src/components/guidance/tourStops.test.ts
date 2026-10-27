import { describe, expect, it } from "vitest";
import {
  INTRO_BY_KEY,
  PAGE_INTROS,
  TOUR_STEPS,
  introForPath,
} from "./tourStops";
import { TOOL_ROWS, buildGrantList } from "@/components/onboarding/steps";
import type { CapabilityInfo } from "@/lib/types";

describe("TOUR_STEPS", () => {
  it("is exactly three steps anchored to Today regions", () => {
    expect(TOUR_STEPS.map((s) => s.anchor)).toEqual([
      "sidebar",
      "needs-you",
      "composer",
    ]);
    expect(TOUR_STEPS[0].eyebrow).toBe("1 of 3");
    expect(TOUR_STEPS[2].eyebrow).toBe("3 of 3");
  });
});

describe("PAGE_INTROS", () => {
  it("covers the seven spec pages", () => {
    expect(PAGE_INTROS.map((d) => d.key).sort()).toEqual(
      ["agents", "channels", "mcps", "scheduler", "skills", "traces", "vault"].sort(),
    );
  });

  it("every card carries the spec shape — eyebrow, title, sub, three facts", () => {
    for (const def of PAGE_INTROS) {
      expect(def.eyebrow.length).toBeGreaterThan(0);
      expect(def.title.length).toBeGreaterThan(0);
      expect(def.sub.length).toBeGreaterThan(0);
      expect(def.facts).toHaveLength(3);
      expect(INTRO_BY_KEY[def.key]).toBe(def);
    }
  });

  it("introForPath matches each route and excludes conversations", () => {
    expect(introForPath("/agents")?.key).toBe("agents");
    expect(introForPath("/traces/caber/abc")?.key).toBe("traces");
    expect(introForPath("/vault/shared")?.key).toBe("vault");
    expect(introForPath("/agents/caber/chat")).toBeUndefined();
    expect(introForPath("/")).toBeUndefined();
    expect(introForPath("/settings")).toBeUndefined();
  });
});

const CAP = (name: string, kind = "tool", require_approval = false): CapabilityInfo => ({
  name,
  kind,
  description: "",
  egress: false,
  require_approval,
  server_id: null,
  server_name: null,
});

describe("buildGrantList", () => {
  const all: CapabilityInfo[] = [
    CAP("web_search", "tool", true),
    CAP("web_fetch", "tool", true),
    CAP("read_file"),
    CAP("write_file"),
    CAP("terminal", "tool", true),
    CAP("memory_recall"), // unmapped — must keep registry defaults
    CAP("some_mcp", "mcp_tool", true), // unmapped mcp tool — registry default
  ];

  it("produces a grant for every listed capability (whitelist semantics)", () => {
    const grants = buildGrantList(all, {});
    expect(grants.map((g) => g.name).sort()).toEqual(
      all.map((c) => c.name).sort(),
    );
  });

  it("maps Allow/Ask/Block onto mapped capabilities", () => {
    const grants = buildGrantList(all, {
      web: "allow",
      read: "allow",
      write: "ask",
      terminal: "block",
      browser: "ask",
    });
    const by = Object.fromEntries(grants.map((g) => [g.name, g]));
    expect(by["web_search"]).toMatchObject({ enabled: true, require_approval: false });
    expect(by["read_file"]).toMatchObject({ enabled: true, require_approval: false });
    expect(by["write_file"]).toMatchObject({ enabled: true, require_approval: true });
    expect(by["terminal"]).toMatchObject({ enabled: false, require_approval: false });
  });

  it("unmapped capabilities keep their registry approval defaults", () => {
    const grants = buildGrantList(all, {});
    const by = Object.fromEntries(grants.map((g) => [g.name, g]));
    expect(by["memory_recall"]).toMatchObject({ enabled: true, require_approval: false });
    expect(by["some_mcp"]).toMatchObject({ enabled: true, require_approval: true });
  });

  it("uses row recommendations when a choice is missing", () => {
    const grants = buildGrantList(all, { web: "block" });
    const by = Object.fromEntries(grants.map((g) => [g.name, g]));
    for (const row of TOOL_ROWS) {
      for (const cap of row.caps) {
        if (row.key === "web" && by[cap]) {
          expect(by[cap]!.enabled).toBe(false);
        } else if (by[cap]) {
          expect(by[cap]!.enabled).toBe(row.recommended !== "block");
          expect(by[cap]!.require_approval).toBe(row.recommended === "ask");
        }
      }
    }
  });
});
