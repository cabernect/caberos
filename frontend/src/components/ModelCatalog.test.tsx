/** W11 catalog UX — ModelPicker seams (per-instance fetches, emit
 * signature, provenance limits, availability text). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelPicker } from "./ModelPicker";
import { api } from "@/lib/api";
import type { ModelInfo, Provider } from "@/lib/types";

const provider: Provider = {
  id: "prov-1",
  name: "OpenAI",
  type: "openai",
  has_key: true,
  base_url: null,
  org_id: null,
  extra_params: {},
  custom_models: [],
  credential_fields: [],
};

const model = (over: Partial<ModelInfo> = {}): ModelInfo => ({
  id: "gpt-6",
  name: "gpt-6",
  ...over,
});

describe("ModelPicker", () => {
  afterEach(() => vi.restoreAllMocks());

  function stubProviders(models: ModelInfo[]) {
    vi.spyOn(api, "listProviders").mockResolvedValue([provider]);
    vi.spyOn(api, "listModels").mockResolvedValue({
      discovery: "dynamic",
      models,
    });
  }

  it("reads the local listing on mount and again on every open", async () => {
    stubProviders([model()]);
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="gpt-6"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText(/gpt-6/));
    await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(2));
  });

  it("forwards the exact request id, not the display name", async () => {
    stubProviders([
      model({ id: "gpt-6", name: "gpt-6", display_name: "GPT Six" }),
    ]);
    const onChange = vi.fn();
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="other"
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalled());
    fireEvent.click(screen.getByText(/Select a model|other/));
    await waitFor(() => expect(screen.getByText(/GPT Six/)).toBeTruthy());
    fireEvent.click(screen.getByText(/GPT Six/));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ provider_id: "prov-1", name: "gpt-6" }),
    );
  });

  it("shows all availability states as text, not color alone", async () => {
    stubProviders([
      model({ id: "gone", name: "gone", availability: "unavailable" }),
      model({
        id: "myst",
        name: "myst",
        availability: "unknown",
        stale: true,
      }),
    ]);
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="gone"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalled());
    fireEvent.click(screen.getByText(/gone/));
    await waitFor(() => expect(screen.getByText(/unavailable/)).toBeTruthy());
    expect(screen.getByText(/unknown · stale/)).toBeTruthy();
  });

  it("does not clobber with a stale out-of-order response", async () => {
    vi.spyOn(api, "listProviders").mockResolvedValue([provider]);
    let release: (v: { discovery: string; models: ModelInfo[] }) => void;
    const first = new Promise<{ discovery: string; models: ModelInfo[] }>(
      (r) => (release = r),
    );
    const spy = vi
      .spyOn(api, "listModels")
      .mockImplementationOnce(() => first)
      .mockResolvedValue({
        discovery: "dynamic",
        models: [model({ id: "new", name: "new" })],
      });

    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="gone"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText(/gone/));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("new")).toBeTruthy());
    release!({
      discovery: "dynamic",
      models: [model({ id: "stale", name: "stale" })],
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("stale")).toBeNull();
    expect(screen.getByText("new")).toBeTruthy();
  });

  it("two selectors on the same provider each receive models", async () => {
    stubProviders([model()]);
    const on1 = vi.fn();
    const on2 = vi.fn();
    render(
      <>
        <ModelPicker
          defaultProviderId="prov-1"
          defaultModelName="gpt-6"
          onChange={on1}
        />
        <ModelPicker
          defaultProviderId="prov-1"
          defaultModelName="gpt-6"
          onChange={on2}
        />
      </>,
    );
    await waitFor(() =>
      expect(on1).toHaveBeenCalledWith(
        expect.objectContaining({ name: "gpt-6" }),
      ),
    );
    await waitFor(() =>
      expect(on2).toHaveBeenCalledWith(
        expect.objectContaining({ name: "gpt-6" }),
      ),
    );
  });

  it("keeps last-known models when a refresh GET fails", async () => {
    vi.spyOn(api, "listProviders").mockResolvedValue([provider]);
    vi.spyOn(api, "listModels")
      .mockResolvedValueOnce({
        discovery: "dynamic",
        models: [model({ id: "keep", name: "keep" })],
      })
      .mockRejectedValueOnce(new Error("500"));
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="keep"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(screen.getByText(/keep/)).toBeTruthy());
    fireEvent.click(screen.getByText(/keep/));
    await waitFor(() =>
      expect(screen.getByText(/refresh failed/)).toBeTruthy(),
    );
    // last-known row still listed
    expect(screen.getByText("keep")).toBeTruthy();
  });

  it("keeps the selected model even when it is unknown", async () => {
    stubProviders([]);
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="custom-model-x"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalled());
    expect(screen.getByText(/custom-model-x/)).toBeTruthy();
  });

  it("re-emits default capabilities when a flag flips at the same row revision", async () => {
    const v1 = [model({ supports_vision: true, revision: 1 })];
    const v2 = [model({ supports_vision: false, revision: 1 })];
    vi.spyOn(api, "listProviders").mockResolvedValue([provider]);
    const spy = vi
      .spyOn(api, "listModels")
      .mockResolvedValueOnce({ discovery: "dynamic", models: v1, revision: "r1" })
      .mockResolvedValue({ discovery: "dynamic", models: v2, revision: "r2" });
    const onChange = vi.fn();
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="gpt-6"
        onChange={onChange}
      />,
    );
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ supports_vision: true }),
      ),
    );
    fireEvent.click(screen.getByText(/gpt-6/));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ supports_vision: false }),
      ),
    );
  });

  it("does not re-emit unchanged capabilities while reopening the selector", async () => {
    vi.spyOn(api, "listProviders").mockResolvedValue([provider]);
    const response = {
      discovery: "dynamic", models: [model({ supports_vision: true })], revision: "unchanged",
    };
    let finish!: (value: typeof response) => void;
    const list = vi.spyOn(api, "listModels")
      .mockResolvedValueOnce(response)
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const onChange = vi.fn();
    render(<ModelPicker defaultProviderId="prov-1" defaultModelName="gpt-6" onChange={onChange} />);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText(/gpt-6/));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    await act(async () => { finish(response); });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("shows input/total/output limits distinctly and Unknown honestly", async () => {
    stubProviders([
      model({
        max_context_tokens: 272000,
        context_window_tokens: null,
        max_output_tokens: null,
        provenance: {
          max_context_tokens: {
            source: "models_dev",
            confidence: "catalog_documented",
          },
          context_window_tokens: { source: "unknown", confidence: "unknown" },
          max_output_tokens: { source: "unknown", confidence: "unknown" },
        },
      }),
    ]);
    render(
      <ModelPicker
        defaultProviderId="prov-1"
        defaultModelName="other"
        onChange={() => {}}
      />,
    );
    await waitFor(() => expect(api.listModels).toHaveBeenCalled());
    fireEvent.click(screen.getByText(/other/));
    await waitFor(() => expect(screen.getByText(/in 272K/)).toBeTruthy());
    const chip = screen.getByText(/in 272K/);
    const title = chip.getAttribute("title") ?? "";
    expect(title).toContain("Input limit: 272,000 tokens");
    expect(title).toContain("Total context: Unknown");
    expect(title).toContain("Output limit: Unknown");
    expect(title).toContain("catalog_documented");
    // context chip must not masquerade as a total-context value
    expect(title).not.toMatch(/Total context: 272/);
  });
});
