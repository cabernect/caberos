/** W5 — global Tools settings tab: engine options editor, save/reset,
 * and honest "not yet available" presentation for planned bindings. */
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { ConfirmProvider } from "@/lib/confirm";
import type { Provider, ToolBindingInfo } from "@/lib/types";
import { ToolsTab } from "./ProvidersSettings";

const ENGINE_SCHEMA = [
  {
    name: "backend",
    kind: "select" as const,
    label: "Search backend",
    default: "ddgs",
    choices: ["ddgs", "tavily", "exa", "firecrawl", "firecrawl_self_hosted", "brave_search"],
    required: false,
  },
  {
    name: "search_depth",
    kind: "select" as const,
    label: "Tavily search depth",
    default: "basic",
    choices: ["basic", "advanced"],
    required: false,
    backends: ["tavily"],
  },
  {
    name: "exa_search_type",
    kind: "select" as const,
    label: "Exa search type",
    default: "auto",
    choices: ["auto", "fast"],
    required: false,
    backends: ["exa"],
  },
  {
    name: "brave_safesearch",
    kind: "select" as const,
    label: "Brave SafeSearch",
    default: "moderate",
    choices: ["off", "moderate", "strict"],
    required: false,
    backends: ["brave_search"],
  },
  {
    name: "engines",
    kind: "engine_order" as const,
    label: "Engines (in try order)",
    default: ["duckduckgo", "brave"],
    choices: ["duckduckgo", "brave", "startpage"],
    required: false,
    backends: ["ddgs"],
  },
  {
    name: "safesearch",
    kind: "select" as const,
    label: "SafeSearch",
    default: "moderate",
    choices: ["on", "moderate", "off"],
    required: false,
    backends: ["ddgs"],
  },
];

const searchTool = (over: Partial<ToolBindingInfo> = {}): ToolBindingInfo => ({
  key: "search.web",
  title: "Web search",
  description: "Engine preference for web_search.",
  kind: "engine",
  implemented: true,
  planned_note: null,
  capability_names: ["web_search"],
  state: "unconfigured",
  ready: true,
  reason: "Using built-in defaults.",
  options: { engines: ["duckduckgo", "brave"], safesearch: "moderate", region: "wt-wt" },
  options_schema: ENGINE_SCHEMA,
  binding: null,
  model_modalities: null,
  ...over,
});

const plannedTool = (key: string, title: string): ToolBindingInfo => ({
  key,
  title,
  description: "Planned media capability.",
  kind: "model",
  implemented: false,
  planned_note: "Planned for a future release.",
  capability_names: [],
  state: "unimplemented",
  ready: false,
  reason: "Not implemented yet.",
  options: {},
  options_schema: [],
  binding: null,
  model_modalities: null,
});

const renderTab = (providers: Provider[] = []) =>
  render(
    <ConfirmProvider>
      <ToolsTab providers={providers} />
    </ConfirmProvider>,
  );

describe("ToolsTab", () => {
  beforeEach(() => {
    vi.spyOn(api, "listProviders").mockResolvedValue([]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the search card and planned media after load", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({
      tools: [searchTool(), plannedTool("media.tts", "Text to speech")],
    });
    renderTab();
    await act(async () => {});
    expect(screen.getByText("Web search")).toBeTruthy();
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByText("Text to speech")).toBeTruthy();
    expect(screen.getByText("Not yet available")).toBeTruthy();
    expect(screen.getByText("Planned for a future release.")).toBeTruthy();
    // Planned cards expose no executable controls.
    expect(screen.queryByText("Choose provider…")).toBeNull();
  });

  it("select options render and update the draft", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({
      tools: [searchTool()],
    });
    renderTab();
    await act(async () => {});
    const trigger = screen.getByRole("button", { name: "SafeSearch" });
    fireEvent.click(trigger);
    await act(async () => {});
    for (const label of ["on", "moderate", "off"]) {
      expect(screen.getByRole("option", { name: label })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole("option", { name: "off" }));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "SafeSearch" }).textContent).toContain("off");
  });

  it("save sends options with expected_revision and re-reads", async () => {
    const list = vi.spyOn(api, "listToolBindings").mockResolvedValue({
      tools: [searchTool()],
    });
    const put = vi
      .spyOn(api, "updateToolBinding")
      .mockResolvedValue(searchTool({ state: "ready" }));
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await act(async () => {});
    expect(put).toHaveBeenCalledTimes(1);
    const [key, body] = put.mock.calls[0];
    expect(key).toBe("search.web");
    expect(body.options?.engines).toEqual(["duckduckgo", "brave"]);
    expect(body.expected_revision).toBeNull(); // unconfigured → no row
    expect(list).toHaveBeenCalledTimes(2); // reload after save
  });

  it("reset goes through confirm then calls the endpoint", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({
      tools: [
        searchTool({
          state: "ready",
          binding: {
            provider_id: null,
            provider_name: null,
            provider_type: null,
            model: "",
            revision: 3,
            updated_at: "2026-01-01T00:00:00Z",
          },
        }),
      ],
    });
    const del = vi
      .spyOn(api, "resetToolBinding")
      .mockResolvedValue(searchTool());
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    await act(async () => {});
    expect(screen.getByText("Reset Web search?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await act(async () => {});
    expect(del).toHaveBeenCalledWith("search.web");
  });

  it("failed load surfaces the error, no crash", async () => {
    vi.spyOn(api, "listToolBindings").mockRejectedValue(new Error("offline"));
    renderTab();
    await act(async () => {});
    expect(screen.getByText(/offline/)).toBeTruthy();
  });

  it("creates an encrypted-provider connection inline then binds search without a model", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool()] });
    const create = vi.spyOn(api, "createProvider").mockResolvedValue({
      id: "tavily-1", name: "Work search", type: "tavily", scope: "search",
      has_key: true, base_url: null, org_id: null, extra_params: {},
      custom_models: [], credential_fields: [],
    });
    const put = vi.spyOn(api, "updateToolBinding").mockResolvedValue(searchTool());
    const probe = vi.spyOn(api, "testSearchProvider");
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Search backend" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("option", { name: "Tavily API" }));
    fireEvent.change(screen.getByLabelText("Connection name"), { target: { value: "Work search" } });
    const key = screen.getByLabelText("Tavily API key");
    expect(key.getAttribute("type")).toBe("password");
    fireEvent.change(key, { target: { value: "test-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await act(async () => {});
    expect(create).toHaveBeenCalledWith({
      name: "Work search", type: "tavily", api_key: "test-key",
    });
    expect(put).toHaveBeenCalledWith("search.web", expect.objectContaining({
      provider_id: "tavily-1", options: expect.objectContaining({ backend: "tavily" }),
    }));
    expect(put.mock.calls[0][1]).not.toHaveProperty("model");
    expect(probe).not.toHaveBeenCalled();
    expect(api.listProviders).toHaveBeenCalledWith("search");
  });

  it("keeps stored keys out of the form and removes them only explicitly", async () => {
    vi.mocked(api.listProviders).mockResolvedValue([{
      id: "tavily-1", name: "Work search", type: "tavily", has_key: true,
      base_url: null, org_id: null, extra_params: {}, custom_models: [], credential_fields: [],
    }]);
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool({
      options: { backend: "tavily" },
      binding: { provider_id: "tavily-1", provider_name: "Work search",
        provider_type: "tavily", model: "", revision: 1, updated_at: null },
    })] });
    const update = vi.spyOn(api, "updateProvider").mockResolvedValue({} as Provider);
    vi.spyOn(api, "updateToolBinding").mockResolvedValue(searchTool());
    renderTab();
    await act(async () => {});
    const keyInput = screen.getByLabelText("Tavily API key") as HTMLInputElement;
    expect(keyInput.value).toBe("");
    expect(keyInput.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await act(async () => {});
    expect(update.mock.calls[0][1]).not.toHaveProperty("api_key");
    expect(update.mock.calls[0][1]).not.toHaveProperty("remove_api_key");
    fireEvent.click(screen.getByRole("button", { name: "Delete key" }));
    await act(async () => {});
    expect(update.mock.calls[1][1].remove_api_key).toBe(true);
    expect((screen.getByLabelText("Tavily API key") as HTMLInputElement).disabled).toBe(false);
  });

  it("requires confirmation before a synthetic potentially paid connection test", async () => {
    vi.mocked(api.listProviders).mockResolvedValue([{
      id: "tavily-1", name: "Work search", type: "tavily", has_key: true,
      base_url: null, org_id: null, extra_params: {}, custom_models: [], credential_fields: [],
    }]);
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool({
      options: { backend: "tavily" },
      binding: { provider_id: "tavily-1", provider_name: "Work search",
        provider_type: "tavily", model: "", revision: 1, updated_at: null },
    })] });
    const probe = vi.spyOn(api, "testSearchProvider").mockResolvedValue({ ok: true, error: null });
    renderTab();
    await act(async () => {});
    expect(probe).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Test connection (may use credits)" }));
    await act(async () => {});
    expect(probe).not.toHaveBeenCalled();
    expect(screen.getByText(/Sends one synthetic query/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await act(async () => {});
    expect(probe).toHaveBeenCalledWith("tavily-1");
    expect(screen.getByRole("status").textContent).toBe("Connection test passed.");
  });

  it("shows Exa connection form and its scoped option, not other backends' options", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool()] });
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Search backend" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("option", { name: "Exa API" }));
    await act(async () => {});
    expect(screen.getByLabelText("Exa API key")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Exa search type" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Tavily search depth" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Brave SafeSearch" })).toBeNull();
    expect(screen.queryByLabelText("Firecrawl server URL")).toBeNull();
  });

  it("saves an Exa connection as an exa-typed provider", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool()] });
    const create = vi.spyOn(api, "createProvider").mockResolvedValue({
      id: "exa-1", name: "Exa search", type: "exa", scope: "search",
      has_key: true, base_url: null, org_id: null, extra_params: {},
      custom_models: [], credential_fields: [],
    });
    const put = vi.spyOn(api, "updateToolBinding").mockResolvedValue(searchTool());
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Search backend" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("option", { name: "Exa API" }));
    fireEvent.change(screen.getByLabelText("Exa API key"), { target: { value: "exa-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await act(async () => {});
    expect(create).toHaveBeenCalledWith({
      name: "Exa search", type: "exa", api_key: "exa-key",
    });
    expect(put).toHaveBeenCalledWith("search.web", expect.objectContaining({
      provider_id: "exa-1", options: expect.objectContaining({ backend: "exa" }),
    }));
  });

  it("self-hosted Firecrawl needs a server URL, key stays optional, private opt-in is explicit", async () => {
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool()] });
    const create = vi.spyOn(api, "createProvider").mockResolvedValue({
      id: "fc-1", name: "Firecrawl self-hosted search", type: "firecrawl_self_hosted",
      scope: "search", has_key: false,
      base_url: "https://firecrawl.lan", org_id: null,
      extra_params: { allow_private_network: true },
      custom_models: [], credential_fields: [],
    });
    vi.spyOn(api, "updateToolBinding").mockResolvedValue(searchTool());
    renderTab();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Search backend" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("option", { name: "Firecrawl self-hosted" }));
    await act(async () => {});
    expect(screen.getByLabelText("Firecrawl server URL")).toBeTruthy();
    expect(screen.getByLabelText("Firecrawl self-hosted API key (optional)")).toBeTruthy();
    // Saving without a URL fails honestly before any request.
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await act(async () => {});
    expect(create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Firecrawl server URL"), {
      target: { value: "https://firecrawl.lan" },
    });
    fireEvent.click(screen.getByLabelText(/Allow private-network addresses/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await act(async () => {});
    expect(create).toHaveBeenCalledWith({
      name: "Firecrawl self-hosted search",
      type: "firecrawl_self_hosted",
      base_url: "https://firecrawl.lan",
      extra_params: { allow_private_network: true },
    });
  });

  it("switching backends drops the previous connection so a mismatched provider can't bind", async () => {
    vi.mocked(api.listProviders).mockResolvedValue([{
      id: "tavily-1", name: "Work search", type: "tavily", has_key: true,
      base_url: null, org_id: null, extra_params: {}, custom_models: [], credential_fields: [],
    }]);
    vi.spyOn(api, "listToolBindings").mockResolvedValue({ tools: [searchTool({
      options: { backend: "tavily" },
      binding: { provider_id: "tavily-1", provider_name: "Work search",
        provider_type: "tavily", model: "", revision: 1, updated_at: null },
    })] });
    renderTab();
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Search connection" }).textContent).toContain("Work search");
    fireEvent.click(screen.getByRole("button", { name: "Search backend" }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("option", { name: "Brave Search API" }));
    await act(async () => {});
    // Brave connection is fresh — no Tavily provider offered, key field required.
    expect(screen.getByRole("button", { name: "Search connection" }).textContent).toContain("New Brave Search connection");
    expect(screen.getByLabelText("Brave Search API key")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Brave SafeSearch" })).toBeTruthy();
  });
});
