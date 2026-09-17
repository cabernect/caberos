import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsOverlay } from "./SettingsOverlay";
import { api } from "@/lib/api";
import type { Agent, CapabilityInfo } from "@/lib/types";

const webSearch: CapabilityInfo = {
  name: "web_search",
  kind: "tool",
  description: "Search the web",
  egress: true,
  require_approval: true,
  server_id: null,
  server_name: null,
};

const mcpTool: CapabilityInfo = {
  name: "mcp.playwright.browser_evaluate",
  kind: "mcp_tool",
  description: "Evaluate JavaScript",
  egress: true,
  require_approval: false,
  server_id: "srv-pw",
  server_name: "Playwright",
};

const baseAgent: Agent = {
  id: "agent-1",
  name: "Test Agent",
  enabled: true,
  model: null,
  provider_id: null,
  soul: "",
  persona: "",
  task: "",
};

function renderCapabilities(agent: Agent, caps: CapabilityInfo[] = [webSearch]) {
  vi.spyOn(api, "getYoloMode").mockResolvedValue({ yolo_mode: false });
  vi.spyOn(api, "listCapabilities").mockResolvedValue(caps);
  render(
    <SettingsOverlay
      agent={agent}
      open
      onClose={vi.fn()}
      onSaved={vi.fn()}
      providers={[]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsOverlay capabilities", () => {
  it("shows built-in approval defaults for all-tools agents", async () => {
    renderCapabilities({ ...baseAgent, capabilities: null });

    expect(await screen.findByLabelText("approval")).toBeChecked();
  });

  it("loads the full agent config when opened from a lightweight agent list", async () => {
    const detailedAgent = {
      ...baseAgent,
      capabilities: [{ name: "web_search", subject: "none" as const, require_approval: false }],
    };
    const getAgent = vi.spyOn(api, "getAgent").mockResolvedValue(detailedAgent);
    renderCapabilities(baseAgent);

    await waitFor(() => expect(getAgent).toHaveBeenCalledWith("agent-1"));
    expect(await screen.findByLabelText("approval")).not.toBeChecked();
  });

  it("shows a retryable error when a capability save is rejected by the API", async () => {
    vi.spyOn(api, "updateAgent").mockRejectedValue(new Error("503: database busy"));
    renderCapabilities({ ...baseAgent, capabilities: null });

    const approval = await screen.findByLabelText("approval");
    fireEvent.click(approval);

    expect(await screen.findByRole("alert")).toHaveTextContent("database is busy");
  });

  it("persists an explicit deny grant when a tool is set to Not permitted under a granted server", async () => {
    const updateAgent = vi.spyOn(api, "updateAgent").mockResolvedValue({ id: baseAgent.id, version: 1, version_id: "v1" });
    renderCapabilities(
      {
        ...baseAgent,
        capabilities: [
          { name: "mcp_server:srv-pw", subject: "none" as const, require_approval: true },
        ],
      },
      [webSearch, mcpTool],
    );

    // Expand the MCP server group to reveal tool rows.
    fireEvent.click(await screen.findByText("MCP: Playwright"));
    const toolRow = (await screen.findByText("mcp.playwright.browser_evaluate")).closest(
      "div.flex.items-center.justify-between",
    )!;
    const select = toolRow.querySelector("select")!;

    fireEvent.change(select, { target: { value: "none" } });

    await waitFor(() => expect(updateAgent).toHaveBeenCalled());
    const saved = updateAgent.mock.calls.at(-1)?.[1]?.capabilities ?? [];
    expect(saved).toContainEqual(
      expect.objectContaining({ name: "mcp_server:srv-pw" }),
    );
    expect(saved).toContainEqual(
      expect.objectContaining({ name: "mcp.playwright.browser_evaluate", enabled: false }),
    );
  });

  it("re-selecting the inherited mode clears the explicit entry", async () => {
    const updateAgent = vi.spyOn(api, "updateAgent").mockResolvedValue({ id: baseAgent.id, version: 1, version_id: "v1" });
    renderCapabilities(
      {
        ...baseAgent,
        capabilities: [
          { name: "mcp_server:srv-pw", subject: "none" as const, require_approval: true },
          { name: "mcp.playwright.browser_evaluate", enabled: false, subject: "none" as const, require_approval: false },
        ],
      },
      [webSearch, mcpTool],
    );

    fireEvent.click(await screen.findByText("MCP: Playwright"));
    const toolRow = (await screen.findByText("mcp.playwright.browser_evaluate")).closest(
      "div.flex.items-center.justify-between",
    )!;
    const select = toolRow.querySelector("select")!;
    // The deny renders as Not permitted under the granted server.
    expect(select).toHaveValue("none");

    fireEvent.change(select, { target: { value: "on_demand" } });

    await waitFor(() => expect(updateAgent).toHaveBeenCalled());
    const saved = updateAgent.mock.calls.at(-1)?.[1]?.capabilities ?? [];
    // Matching the inherited mode drops the explicit entry entirely.
    expect(saved).not.toContainEqual(
      expect.objectContaining({ name: "mcp.playwright.browser_evaluate" }),
    );
  });
});
