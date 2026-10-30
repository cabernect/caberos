import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dismissAllIntros,
  getSeenIntros,
  getTourState,
  getWizardState,
  introsDismissed,
  markIntroSeen,
  onGuidanceChange,
  resetGuidance,
  setTourState,
  setWizardState,
} from "./guidanceState";

describe("guidanceState", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("starts with wizard pending and tour offered", () => {
    expect(getWizardState()).toBe("pending");
    expect(getTourState()).toBe("offered");
  });

  it("persists wizard and tour states", () => {
    setWizardState("done");
    setTourState("active");
    expect(getWizardState()).toBe("done");
    expect(getTourState()).toBe("active");
  });

  it("tracks seen intros per page and dismisses all", () => {
    markIntroSeen("agents");
    markIntroSeen("traces");
    expect(getSeenIntros()).toEqual(new Set(["agents", "traces"]));
    expect(introsDismissed()).toBe(false);
    dismissAllIntros();
    expect(introsDismissed()).toBe(true);
  });

  it("resetGuidance re-arms every flag", () => {
    setWizardState("skipped");
    setTourState("done");
    dismissAllIntros();
    resetGuidance();
    expect(getWizardState()).toBe("pending");
    expect(getTourState()).toBe("offered");
    expect(introsDismissed()).toBe(false);
    expect(getSeenIntros().size).toBe(0);
  });

  it("emits a change event on every mutation", () => {
    const listener = vi.fn();
    const off = onGuidanceChange(listener);
    setWizardState("done");
    setTourState("skipped");
    markIntroSeen("today");
    resetGuidance();
    expect(listener).toHaveBeenCalledTimes(4);
    off();
    setWizardState("pending");
    expect(listener).toHaveBeenCalledTimes(4);
  });
});
