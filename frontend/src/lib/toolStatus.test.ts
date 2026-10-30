import { describe, expect, it } from "vitest";
import { toolEventStatus } from "./toolStatus";

describe("toolEventStatus", () => {
  it("maps outcomes to display status; failed !== denied", () => {
    expect(toolEventStatus("ok")).toBe("complete");
    expect(toolEventStatus("denied")).toBe("denied");
    expect(toolEventStatus("error")).toBe("failed");
    expect(toolEventStatus("timeout")).toBe("timeout");
    expect(toolEventStatus("interrupted")).toBe("interrupted");
    expect(toolEventStatus("error")).not.toBe("denied");
    expect(toolEventStatus("mysterious")).toBe("failed");
    expect(toolEventStatus(undefined)).toBe("failed");
  });
});
