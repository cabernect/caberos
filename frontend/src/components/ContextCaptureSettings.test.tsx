import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import { ContextCaptureSettings } from "./ContextCaptureSettings";

vi.mock("@/lib/api", () => ({
  api: {
    getContextCapturePolicy: vi.fn(),
    updateContextCapturePolicy: vi.fn(),
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const policy = {
  retention_days: 7,
  max_bytes: 268435456,
  max_payload_bytes: 1048576,
  pinned: { retention_days: false, max_bytes: false, max_payload_bytes: true },
};

describe("ContextCaptureSettings policy", () => {
  it("fetches the policy on mount and shows current values", async () => {
    const getPolicy = vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(policy);
    render(<ContextCaptureSettings />);
    await waitFor(() => expect(getPolicy).toHaveBeenCalledTimes(1));
    expect(await screen.findByDisplayValue("7")).toBeInTheDocument();
    // Per-request cap is env-pinned → disabled + flagged; others editable.
    expect(screen.getByLabelText(/Total cap/)).not.toBeDisabled();
    expect(screen.getByLabelText(/Per-request cap/)).toBeDisabled();
    expect(screen.getByText("Pinned by environment")).toBeInTheDocument();
  });

  it("rejects invalid input rather than silently clamping", async () => {
    vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(policy);
    const put = vi.spyOn(api, "updateContextCapturePolicy").mockResolvedValue({});
    render(<ContextCaptureSettings />);
    fireEvent.change(await screen.findByLabelText(/Retention window/), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(put).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/positive whole number/),
    ).toBeInTheDocument();
  });

  it("unchanged pinned value does not block saving an unpinned field", async () => {
    const pinnedPolicy = {
      ...policy,
      pinned: { retention_days: true, max_bytes: false, max_payload_bytes: false },
    };
    vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(pinnedPolicy);
    const put = vi
      .spyOn(api, "updateContextCapturePolicy")
      .mockResolvedValue({ ok: true } as never);
    render(<ContextCaptureSettings />);
    await screen.findByDisplayValue("7");
    expect(screen.getByLabelText(/Retention window/)).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Total cap/), {
      target: { value: "512" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = (put.mock.calls[0][0] ?? {}) as Record<string, number>;
    expect(body.retention_days).toBe(7); // pinned value sent unchanged
    expect(body.max_bytes).toBe(512 * 1048576);
    expect(body.max_payload_bytes).toBe(1048576);
  });
});
