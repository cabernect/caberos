import { describe, expect, it, vi } from "vitest";
import { openUrl } from "./openUrl";

describe("openUrl", () => {
  it("does not open unsupported protocols", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    await openUrl("javascript:alert(1)");
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it("opens HTTP URLs with a protected window", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    await openUrl("https://example.com/docs");
    expect(open).toHaveBeenCalledWith("https://example.com/docs", "_blank", "noopener,noreferrer");
    open.mockRestore();
  });
});
