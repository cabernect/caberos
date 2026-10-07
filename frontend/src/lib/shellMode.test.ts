import { describe, expect, it } from "vitest";
import { PHONE_MAX_WIDTH, TABLET_MAX_WIDTH, shellModeFor } from "./shellMode";

describe("shellModeFor", () => {
  it("is a phone shell up to and including the phone breakpoint", () => {
    expect(shellModeFor(320)).toBe("phone");
    expect(shellModeFor(390)).toBe("phone");
    expect(shellModeFor(PHONE_MAX_WIDTH)).toBe("phone");
  });

  it("is a tablet shell between the breakpoints", () => {
    expect(shellModeFor(PHONE_MAX_WIDTH + 1)).toBe("tablet");
    expect(shellModeFor(820)).toBe("tablet");
    expect(shellModeFor(TABLET_MAX_WIDTH)).toBe("tablet");
  });

  it("is a desktop shell above the tablet breakpoint", () => {
    expect(shellModeFor(TABLET_MAX_WIDTH + 1)).toBe("desktop");
    expect(shellModeFor(1280)).toBe("desktop");
    expect(shellModeFor(2560)).toBe("desktop");
  });
});
