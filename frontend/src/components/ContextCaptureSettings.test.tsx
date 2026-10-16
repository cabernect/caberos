import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function renderSection() {
  render(<ContextCaptureSettings />);
}
describe("ContextCaptureSettings policy", () => {
  const policy = {
    retention_days: 7,
    max_bytes: 268435456,
    max_payload_bytes: 1048576,
    pinned: { retention_days: false, max_bytes: false, max_payload_bytes: true },
  };

  it("fetches policy only when expanded and shows current values", async () => {
    const getPolicy = vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(policy);
    renderSection();
    expect(getPolicy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Request capture retention/ }));
    await waitFor(() => expect(getPolicy).toHaveBeenCalled());
    const dayInput = screen.getByDisplayValue("7");
    expect(dayInput).toBeInTheDocument();
    // Per-request cap is env-pinned → disabled; the others are editable.
    const mib = screen.getByDisplayValue("256");
    expect(mib).not.toBeDisabled();
    const kib = screen.getByDisplayValue("1024");
    expect(kib).toBeDisabled();
  });

  it("rejects invalid input rather than silently clamping", async () => {
    vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(policy);
    const put = vi.spyOn(api, "updateContextCapturePolicy").mockResolvedValue({});
    renderSection();
    fireEvent.click(screen.getByRole("button", { name: /Request capture retention/ }));
    await screen.findByDisplayValue("7");
    fireEvent.change(screen.getByDisplayValue("7"), { target: { value: "abc" } });
    const section = screen.getByText(/Retention \(days\)/).closest("div")!.parentElement!;
    fireEvent.click(within(section).getByRole("button", { name: "Save" }));
    expect(put).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/positive whole number/),
    ).toBeInTheDocument();
  });
});

describe("ContextCaptureSettings lifecycle", () => {
  const pinnedPolicy = {
    retention_days: 7,
    max_bytes: 268435456,
    max_payload_bytes: 1048576,
    pinned: { retention_days: true, max_bytes: false, max_payload_bytes: false },
  };

  it("reopen after a pending fetch still resolves", async () => {
    const resolvers: Array<(v: typeof pinnedPolicy) => void> = [];
    vi.spyOn(api, "getContextCapturePolicy").mockImplementation(
      () =>
        new Promise((res) => {
          resolvers.push(res);
        }),
    );
    renderSection();
    const toggle = screen.getByRole("button", { name: /Request capture retention/ });
    fireEvent.click(toggle); // open → fetch #1 starts
    fireEvent.click(toggle); // close before it resolves
    resolvers[0](pinnedPolicy); // stale response lands while closed — dropped
    fireEvent.click(toggle); // reopen → fetch #2 (fresh request)
    await waitFor(() => expect(resolvers.length).toBeGreaterThanOrEqual(2));
    resolvers[1](pinnedPolicy);
    expect(await screen.findByDisplayValue("7")).toBeInTheDocument();
  });

  it("unchanged pinned value does not block saving an unpinned field", async () => {
    vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue(pinnedPolicy);
    const put = vi
      .spyOn(api, "updateContextCapturePolicy")
      .mockResolvedValue({ ok: true } as never);
    renderSection();
    fireEvent.click(
      screen.getByRole("button", { name: /Request capture retention/ }),
    );
    await screen.findByDisplayValue("7");
    // Pinned field is disabled; the others stay editable.
    expect(screen.getByLabelText(/Retention \(days\)/)).toBeDisabled();
    // Edit the unpinned total cap only.
    fireEvent.change(screen.getByLabelText(/Total cap \(MiB\)/), {
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
