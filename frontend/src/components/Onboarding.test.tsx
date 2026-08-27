import { describe, expect, it } from "vitest";
import { needsOnboarding } from "./onboardingEligibility";

const provider = { id: "p1", name: "OpenAI", type: "openai", has_key: true };


describe("onboarding eligibility", () => {
  it("starts when there is no usable provider", () => {
    expect(needsOnboarding([], [])).toBe(true);
    expect(needsOnboarding([{ ...provider, has_key: false }], [])).toBe(true);
  });

  it("does not start after a configured provider and agent exist", () => {
    expect(needsOnboarding([provider], [{ id: "a1" }])).toBe(false);
  });
});
