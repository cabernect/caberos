import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsOverlay } from "./SettingsOverlay";
import { api, ApiError } from "@/lib/api";
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
    vi.spyOn(api, "updateAgent").mockRejectedValue(new ApiError(503, "database busy"));
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
    const select = toolRow.querySelector('button[aria-haspopup="listbox"]')!;

    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: "Not permitted" }));

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
    const select = toolRow.querySelector('button[aria-haspopup="listbox"]')!;
    // The deny renders as Not permitted under the granted server.
    expect(select).toHaveTextContent("Not permitted");

    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: "On demand" }));

    await waitFor(() => expect(updateAgent).toHaveBeenCalled());
    const saved = updateAgent.mock.calls.at(-1)?.[1]?.capabilities ?? [];
    // Matching the inherited mode drops the explicit entry entirely.
    expect(saved).not.toContainEqual(
      expect.objectContaining({ name: "mcp.playwright.browser_evaluate" }),
    );
  });
});

// --- Memory tab (bounded core) ---

function renderMemoryTab() {
  vi.spyOn(api, "getYoloMode").mockResolvedValue({ yolo_mode: false });
  vi.spyOn(api, "listCapabilities").mockResolvedValue([]);
  render(
    <SettingsOverlay agent={baseAgent} open onClose={vi.fn()} onSaved={vi.fn()} providers={[]} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Memory" }));
}

const loadedMemory = {
  content:
    "<!-- caberos:core-identity v1 sha256:abc -->\n## Soul\n\nS\n<!-- /caberos:core-identity -->\n\n- prefers tea",
  exists: true,
  curated_content: "- prefers tea",
  managed_content:
    "<!-- caberos:core-identity v1 sha256:abc -->\n## Soul\n\nS\n<!-- /caberos:core-identity -->",
  hash: "whole-hash-1",
  token_count: 42,
  max_tokens: 4096,
  revision_id: "core-rev-1",
};

describe("SettingsOverlay memory tab", () => {
  it("shows read-only managed identity and editable curated text", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    renderMemoryTab();
    expect(await screen.findByText("Managed identity (read-only)")).toBeInTheDocument();
    const ta = screen.getByPlaceholderText(/Durable preferences/) as HTMLTextAreaElement;
    expect(ta.value).toBe("- prefers tea");
    expect(screen.getByText(/42 \/ 4096 tokens/)).toBeInTheDocument();
  });

  it("passes the whole-file hash as CAS base on save", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    const update = vi
      .spyOn(api, "updateMemory")
      .mockResolvedValue({ ok: true, revision_id: "core-rev-2", token_count: 40, hash: "h2" });
    renderMemoryTab();
    const ta = await screen.findByPlaceholderText(/Durable preferences/);
    fireEvent.change(ta, { target: { value: "- prefers coffee" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("agent-1", "- prefers coffee", "whole-hash-1"),
    );
  });

  it("surfaces conflict detail with current curated on CAS loss", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    vi.spyOn(api, "updateMemory").mockRejectedValue(
      new ApiError(409, "conflict", undefined, {
        conflict: "Core changed since your edit base",
        current_hash: "h-new",
        current_curated_content: "- someone else edited",
      }),
    );
    renderMemoryTab();
    const ta = await screen.findByPlaceholderText(/Durable preferences/);
    fireEvent.change(ta, { target: { value: "mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(/Core changed since your edit base/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Replace my draft/)).toBeInTheDocument();
  });

  it("disables Clean Up while the draft is dirty and runs cleanup when saved", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    const cleanup = vi.spyOn(api, "cleanupMemory").mockResolvedValue({ ok: true });
    renderMemoryTab();
    const cleanupBtn = await screen.findByRole("button", { name: "Clean Up" });
    expect(cleanupBtn).not.toBeDisabled();
    const ta = screen.getByPlaceholderText(/Durable preferences/);
    fireEvent.change(ta, { target: { value: "unsaved draft" } });
    await waitFor(() => expect(cleanupBtn).toBeDisabled());
    fireEvent.change(ta, { target: { value: "- prefers tea" } });
    await waitFor(() => expect(cleanupBtn).not.toBeDisabled());
    fireEvent.click(cleanupBtn);
    await waitFor(() => expect(cleanup).toHaveBeenCalledWith("agent-1"));
  });

  it("keeps the draft and shows the error when load fails", async () => {
    vi.spyOn(api, "getMemory").mockRejectedValue(new ApiError(500, "db down"));
    renderMemoryTab();
    expect(await screen.findByText(/db down/)).toBeInTheDocument();
    const ta = screen.getByPlaceholderText(/Durable preferences/) as HTMLTextAreaElement;
    // Draft preserved — user can still type; nothing stomped it.
    fireEvent.change(ta, { target: { value: "keep me" } });
    expect(ta.value).toBe("keep me");
  });

  it("adopts the server hash+curated on Replace my draft so retry succeeds", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    const update = vi
      .spyOn(api, "updateMemory")
      .mockRejectedValueOnce(
        new ApiError(409, "conflict", undefined, {
          conflict: "Core changed since your edit base",
          current_hash: "h2-server",
          current_curated_content: "- server body",
        }),
      )
      .mockResolvedValueOnce({ ok: true, revision_id: "core-rev-9", token_count: 11, hash: "h3" });
    renderMemoryTab();
    const ta = await screen.findByPlaceholderText(/Durable preferences/);
    fireEvent.change(ta, { target: { value: "mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/Replace my draft/);
    fireEvent.click(screen.getByRole("button", { name: /Replace my draft/ }));
    // Curated bytes adopted, hash base moved to h2-server; edit then save.
    expect((ta as HTMLTextAreaElement).value).toBe("- server body");
    fireEvent.change(ta, { target: { value: "- merged" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(update).toHaveBeenLastCalledWith("agent-1", "- merged", "h2-server"),
    );
  });
});

describe("SettingsOverlay capture retention placement", () => {
  it("the agent Memory tab shows NO installation-wide retention controls", async () => {
    vi.spyOn(api, "getMemory").mockResolvedValue(loadedMemory);
    const getPolicy = vi.spyOn(api, "getContextCapturePolicy").mockResolvedValue({
      retention_days: 7,
      max_bytes: 268435456,
      max_payload_bytes: 1048576,
      pinned: { retention_days: false, max_bytes: false, max_payload_bytes: false },
    });
    renderMemoryTab();
    await screen.findByPlaceholderText(/Durable preferences/);
    // Capture retention is installation-wide — it lives in global
    // Settings, never inside a single agent's overlay.
    expect(screen.queryByRole("button", { name: /Request capture retention/ })).toBeNull();
    expect(getPolicy).not.toHaveBeenCalled();
  });
});
