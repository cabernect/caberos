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

function renderCapabilities(agent: Agent) {
  vi.spyOn(api, "getYoloMode").mockResolvedValue({ yolo_mode: false });
  vi.spyOn(api, "listCapabilities").mockResolvedValue([webSearch]);
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
});
