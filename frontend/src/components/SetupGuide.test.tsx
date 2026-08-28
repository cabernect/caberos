import { beforeEach, describe, expect, it } from "vitest";
import {
  dismissSetupGuide,
  getSetupGuidePhase,
  setSetupGuidePhase,
  shouldShowSetupGuide,
} from "./setupGuideState";

describe("setup guide state", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("starts for an unconfigured workspace", () => {
    expect(getSetupGuidePhase()).toBe(0);
    expect(shouldShowSetupGuide(false)).toBe(true);
  });

  it("keeps the guide available while setup is in progress", () => {
    setSetupGuidePhase(2);
    expect(getSetupGuidePhase()).toBe(2);
    expect(shouldShowSetupGuide(true)).toBe(true);
  });

  it("can be dismissed without affecting configured workspaces", () => {
    dismissSetupGuide();
    expect(shouldShowSetupGuide(false)).toBe(false);
    expect(shouldShowSetupGuide(true)).toBe(false);
  });
});
