import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { SpendSection } from "./Observability";

const agentSpend = {
  total_cost: 0.5,
  total_runs: 2,
  total_tokens_in: 100,
  total_tokens_out: 40,
  by_agent: [
    { agent_id: "a1", agent_name: "Caber", total_cost: 0.5, run_count: 2, tokens_in: 100, tokens_out: 40 },
  ],
  by_trigger: { dashboard: 0.5 },
};

const platformSpend = {
  scope: "platform" as const,
  since: "2024-01-01",
  until: "2024-02-01",
  total_cost: 0.05,
  total_calls: 6,
  total_runs: 1,
  total_tokens_in: 700,
  total_tokens_out: 137,
  thinking_tokens: 30,
  cached_tokens: null,
  priced_calls: 4,
  unpriced_calls: 2,
  thinking_reported_calls: 3,
  by_agent: [],
  by_provider: [
    { provider_id: "p-uuid-1", call_count: 4, run_count: 1, total_cost: 0.05, tokens_in: 500, tokens_out: 120, thinking_tokens: 30, priced_calls: 4, unpriced_calls: 0, thinking_reported_calls: 3 },
    { provider_id: "p-uuid-2", call_count: 2, run_count: 0, total_cost: 0.0, tokens_in: 200, tokens_out: 17, thinking_tokens: null, priced_calls: 0, unpriced_calls: 2, thinking_reported_calls: 0 },
  ],
  by_model: [
    { provider_id: "p-uuid-1", model_name: "gpt-5.2", call_count: 2, run_count: 1, total_cost: 0.04, tokens_in: 400, tokens_out: 100, thinking_tokens: 30, priced_calls: 2, unpriced_calls: 0, thinking_reported_calls: 2 },
    { provider_id: "p-uuid-2", model_name: "gpt-5.2", call_count: 1, run_count: 0, total_cost: 0.0, tokens_in: 10, tokens_out: 5, thinking_tokens: null, priced_calls: 0, unpriced_calls: 1, thinking_reported_calls: 0 },
  ],
  by_kind: [{ kind: "chat", call_count: 2, run_count: 1, total_cost: 0.05, tokens_in: 500, tokens_out: 120, thinking_tokens: 30, priced_calls: 2, unpriced_calls: 0, thinking_reported_calls: 2 }],
};

const PROVIDERS = [
  { id: "p-uuid-1", name: "OpenAI" },
  { id: "p-uuid-2", name: "Ollama" },
];

vi.mock("@/lib/api", () => ({
  api: {
    getSpend: vi.fn(),
    getPlatformSpend: vi.fn(),
    listAgents: vi.fn(async () => []),
    listProviders: vi.fn(async () => PROVIDERS),
  },
}));

import { api } from "@/lib/api";

async function openPlatform() {
  fireEvent.click(screen.getByRole("button", { name: "Platform" }));
  await waitFor(() => expect(api.getPlatformSpend).toHaveBeenCalled());
}

describe("SpendSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getSpend as any).mockResolvedValue(agentSpend);
    (api.getPlatformSpend as any).mockResolvedValue(platformSpend);
  });

  it("agent scope renders agent + trigger tables", async () => {
    render(<SpendSection days={7} agents={[{ id: "a1", name: "Caber" } as any]} />);
    await waitFor(() => screen.getByText("By trigger"));
    expect(api.getSpend).toHaveBeenCalledWith(7, undefined);
    expect(screen.getByText("dashboard")).toBeInTheDocument();
  });

  it("platform scope shows kind labels and provider/model rows with coverage", async () => {
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("By kind"));
    expect(screen.getAllByText("Chat").length).toBeGreaterThan(0);
    // provider names resolve — no raw UUID as primary label
    expect(screen.getAllByText("OpenAI").length).toBeGreaterThan(0);
    expect(screen.queryByText(/p-uuid-1/)).not.toBeInTheDocument();
    // same model name from two providers stays two rows
    expect(screen.getAllByText("gpt-5.2").length).toBe(2);
    expect(screen.getAllByText("Ollama").length).toBeGreaterThan(0);
    // partial pricing is flagged, not shown as a precise total
    expect(screen.getByText(/pricing unavailable for 2 of 6 calls/)).toBeInTheDocument();
    expect(screen.getAllByText(/\$0\.05/).length).toBeGreaterThan(0);
  });

  it("all-unpriced calls show Unknown, never a fake $0 total", async () => {
    (api.getPlatformSpend as any).mockResolvedValue({
      ...platformSpend,
      total_cost: 0.0,
      total_calls: 31,
      priced_calls: 0,
      unpriced_calls: 31,
    });
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("Unknown"));
    expect(screen.getByText(/Actual spend is unknown: 31 of 31 calls lack pricing data/)).toBeInTheDocument();
    expect(screen.getByText("$0.000000 recorded")).toBeInTheDocument();
  });

  it("fully priced calls (incl. explicit zero) show the recorded total", async () => {
    (api.getPlatformSpend as any).mockResolvedValue({
      ...platformSpend,
      total_cost: 0.0,
      total_calls: 2,
      priced_calls: 2,
      unpriced_calls: 0,
      thinking_reported_calls: 1,
      thinking_tokens: 0,
    });
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getAllByText("$0.000000"));
    expect(screen.queryByText(/lack pricing data/)).not.toBeInTheDocument();
    // explicit zero thinking stays 0
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
  });

  it("thinking null → Not reported, coverage count surfaced", async () => {
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("By model"));
    expect(screen.getAllByText("30").length).toBeGreaterThan(0); // reported thinking
    expect(screen.getByText(/3 of 6 calls/)).toBeInTheDocument(); // coverage
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0); // null cells
  });

  it("older backend without coverage fields gets the honest fallback", async () => {
    const { priced_calls, unpriced_calls, thinking_reported_calls, ...old } = platformSpend;
    void priced_calls; void unpriced_calls; void thinking_reported_calls;
    (api.getPlatformSpend as any).mockResolvedValue({
      ...old,
      by_provider: old.by_provider.map((r) => ({ ...r, priced_calls: undefined, unpriced_calls: undefined })),
      by_model: old.by_model.map((r) => ({ ...r, priced_calls: undefined, unpriced_calls: undefined })),
      by_kind: old.by_kind.map((r) => ({ ...r, priced_calls: undefined, unpriced_calls: undefined })),
    });
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("Pricing coverage unavailable."));
    expect(screen.getAllByText("Recorded cost").length).toBeGreaterThan(0);
  });

  it("provider filter sends the provider ID, not its display name", async () => {
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("By kind"));
    const selects = screen.getAllByRole("combobox");
    const providerSelect = selects.find((s) =>
      [...(s as HTMLSelectElement).options].some((o) => o.textContent === "OpenAI"),
    )!;
    fireEvent.change(providerSelect, { target: { value: "p-uuid-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(api.getPlatformSpend).toHaveBeenLastCalledWith(
        expect.objectContaining({ provider_id: "p-uuid-1" }),
      ),
    );
  });

  it("a failed request clears the previous payload", async () => {
    render(<SpendSection days={7} agents={[]} />);
    await waitFor(() => screen.getByText("By agent"));
    (api.getSpend as any).mockRejectedValueOnce(new Error("boom"));
    fireEvent.change(screen.getByLabelText("Agent"), { target: { value: "a1" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => screen.getByText(/Couldn't load spend/));
    expect(screen.queryByText("By trigger")).not.toBeInTheDocument();
  });

  it("scope toggle never shows the other scope's payload", async () => {
    let resolvePlatform: (v: any) => void = () => {};
    (api.getPlatformSpend as any).mockImplementation(
      () => new Promise((r) => (resolvePlatform = r)),
    );
    render(<SpendSection days={7} agents={[]} />);
    await waitFor(() => screen.getByText("By agent"));
    fireEvent.click(screen.getByRole("button", { name: "Platform" }));
    await act(async () => resolvePlatform(platformSpend));
    await waitFor(() => screen.getByText("By kind"));
    fireEvent.click(screen.getByRole("button", { name: "Agent" }));
    await waitFor(() => screen.getByText("By trigger"));
    expect(screen.queryByText("By kind")).not.toBeInTheDocument();
  });
});

describe("providerLabel collisions", () => {
  it("same-name providers get a short-id suffix", async () => {
    (api.getSpend as any).mockResolvedValue(agentSpend);
    (api.getPlatformSpend as any).mockResolvedValue(platformSpend);
    (api.listProviders as any).mockResolvedValue([
      { id: "p-uuid-1", name: "Same" },
      { id: "p-uuid-2", name: "Same" },
    ]);
    render(<SpendSection days={7} agents={[]} />);
    await openPlatform();
    await waitFor(() => screen.getByText("By model"));
    // both remain distinct, suffixed with their short ids — not merged
    expect(screen.getAllByText("Same · p-uuid-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Same · p-uuid-2").length).toBeGreaterThan(0);
  });
});
