/** W5 — global Tools settings tab: engine options editor, save/reset,
 * and honest "not yet available" presentation for planned bindings. */
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { ConfirmProvider } from "@/lib/confirm";
import type { Provider, ToolBindingInfo } from "@/lib/types";
import { ToolsTab } from "./ProvidersSettings";

const ENGINE_SCHEMA = [
  {
    name: "engines",
    kind: "engine_order" as const,
    label: "Engines (in try order)",
    default: ["duckduckgo", "brave"],
    choices: ["duckduckgo", "brave", "startpage"],
    required: false,
  },
  {
    name: "safesearch",
    kind: "select" as const,
    label: "SafeSearch",
    default: "moderate",
    choices: ["on", "moderate", "off"],
    required: false,
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
});

const renderTab = (providers: Provider[] = []) =>
  render(
    <ConfirmProvider>
      <ToolsTab providers={providers} />
    </ConfirmProvider>,
  );

describe("ToolsTab", () => {
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
    const trigger = screen.getByRole("button", { name: "moderate" });
    fireEvent.click(trigger);
    await act(async () => {});
    for (const label of ["on", "moderate", "off"]) {
      expect(screen.getByRole("option", { name: label })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole("option", { name: "off" }));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "off" })).toBeTruthy();
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
});
