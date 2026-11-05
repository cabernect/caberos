import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { ConfirmProvider } from "@/lib/confirm";
import type { McpCatalogEntry, McpServerInfo } from "@/lib/types";
import { Mcps } from "./Mcps";

vi.mock("@/components/DashboardSidebar", () => ({
  DashboardSidebar: () => null,
  NAV_ROUTES: {},
}));
vi.mock("@/components/guidance/PageIntro", () => ({ PageIntro: () => null }));

const entry: McpCatalogEntry = {
  name: "Exa", category: "search", description: "Search with Exa",
  transport: "http", command: null, args: null, url: "https://mcp.exa.ai/mcp",
  auth_type: "oauth", env_template: null, headers: null, vendor: "Exa",
  homepage: "https://exa.ai",
};

const serverRow = (overrides: Partial<McpServerInfo>): McpServerInfo => ({
  id: "srv", name: "Exa", transport: "http", command: null, args: null,
  url: "https://mcp.exa.ai/mcp", enabled: true, connected: false,
  connect_error: null, tool_count: 0, tool_filter: null, require_approval: true,
  env_template: null, headers_template: null, oauth_config: null,
  auth_type: "none", has_credentials: false, created_at: null, ...overrides,
});

const renderPage = () =>
  render(<MemoryRouter><ConfirmProvider><Mcps /></ConfirmProvider></MemoryRouter>);

const openCatalog = async (overrides: Partial<McpCatalogEntry> = {}) => {
  vi.spyOn(api, "listMcpServers").mockResolvedValue([]);
  vi.spyOn(api, "listMcpCatalog").mockResolvedValue([{ ...entry, ...overrides }]);
  renderPage();
  await act(async () => {});
  fireEvent.click(screen.getAllByRole("button", { name: /Browse catalog/ })[0]);
  await act(async () => {});
};

describe("MCP catalog install", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["oauth", "api_key", "none"] as const)(
    "installs a %s server directly — no credential dialog",
    async (authType) => {
      const install = vi.spyOn(api, "installFromCatalog").mockResolvedValue({
        id: "exa", name: "Exa", connected: false, auth_type: authType, message: null,
      });
      await openCatalog({ auth_type: authType });
      fireEvent.click(screen.getByRole("button", { name: "Install" }));
      await act(async () => {});
      expect(install).toHaveBeenCalledExactlyOnceWith("Exa");
      expect(screen.queryByLabelText("API key")).toBeNull();
    },
  );

  it("labels a dual-auth entry as OAuth or API key", async () => {
    await openCatalog({
      auth_type: "oauth",
      headers: { "x-api-key": "{{credential_value}}" },
    });
    expect(screen.getByText("OAuth or API key")).toBeTruthy();
  });
});

describe("MCP server auth actions", () => {
  afterEach(() => vi.restoreAllMocks());

  const showServer = async (server: McpServerInfo) => {
    vi.spyOn(api, "listMcpServers").mockResolvedValue([server]);
    vi.spyOn(api, "listMcpCatalog").mockResolvedValue([]);
    vi.spyOn(api, "getMcpServerBlastRadius").mockResolvedValue([]);
    vi.spyOn(api, "listMcpServerTools").mockResolvedValue([]);
    vi.spyOn(api, "listMcpCredentials").mockResolvedValue([]);
    renderPage();
    await act(async () => {});
    fireEvent.click(screen.getByText("Exa", { selector: "span.truncate" }));
    await act(async () => {});
  };

  it("presents OAuth as primary and a key as the alternative on a dual-auth server", async () => {
    await showServer(serverRow({
      auth_type: "oauth",
      oauth_config: { scope: "mcp:tools" },
      headers_template: { "x-api-key": "{{credential_value}}" },
    }));
    expect(screen.getByRole("button", { name: /Connect OAuth/ })).toBeTruthy();
    // Either method suffices — one key action, framed as the alternative.
    expect(screen.getAllByRole("button", { name: /Set API key/ })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Add key" })).toBeNull();
    expect(screen.getByText(/either method connects/)).toBeTruthy();
    expect(screen.queryByText(/needs an API key/)).toBeNull();
  });

  it("starts the OAuth flow and opens the provider page", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    vi.spyOn(api, "startMcpOAuth").mockResolvedValue({
      authorize_url: "https://auth.exa.ai/oauth/authorize?x=1",
    });
    vi.spyOn(api, "getMcpOAuthStatus").mockResolvedValue({ status: "pending" });
    await showServer(serverRow({
      auth_type: "oauth", oauth_config: { scope: "mcp:tools" },
    }));
    fireEvent.click(screen.getByRole("button", { name: /Connect OAuth/ }));
    await act(async () => {});
    expect(api.startMcpOAuth).toHaveBeenCalledWith("srv");
    expect(open).toHaveBeenCalledWith(
      "https://auth.exa.ai/oauth/authorize?x=1", "_blank", "noopener,noreferrer",
    );
  });

  it("offers key entry for an installed keyed HTTP server", async () => {
    const save = vi.spyOn(api, "storeMcpCredential").mockResolvedValue({
      id: "key", credential_type: "api_key", label: null, connected: false,
    });
    await showServer(serverRow({
      id: "legacy", auth_type: "api_key", enabled: false,
      headers_template: { "x-api-key": "{{credential_value}}" },
    }));
    expect(screen.getAllByRole("button", { name: /key/i })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Set API key" }));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "synthetic-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await act(async () => {});
    expect(save).toHaveBeenCalledWith("legacy", {
      credential_type: "api_key", value: "synthetic-key",
    });
  });
});

describe("MCP add-server JSON paste", () => {
  afterEach(() => vi.restoreAllMocks());

  const openAddModal = async () => {
    vi.spyOn(api, "listMcpServers").mockResolvedValue([]);
    vi.spyOn(api, "listMcpCatalog").mockResolvedValue([]);
    renderPage();
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Add server/ }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Paste JSON" }));
  };

  const jsonInput = () => screen.getByPlaceholderText(/"name"/);

  it("passes declared auth through to the server create call", async () => {
    const create = vi.spyOn(api, "createMcpServer").mockResolvedValue({
      id: "exa", name: "exa", connected: false,
    });
    await openAddModal();
    fireEvent.change(jsonInput(), {
      target: { value: JSON.stringify({
        exa: { url: "https://mcp.exa.ai/mcp?login", transport: "http", auth: "oauth" },
      }) },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add server" }).at(-1)!);
    await act(async () => {});
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "exa", url: "https://mcp.exa.ai/mcp?login",
        transport: "http", auth: "oauth",
      }),
    );
  });

  it("maps standard-format 'type' onto transport", async () => {
    const create = vi.spyOn(api, "createMcpServer").mockResolvedValue({
      id: "exa", name: "exa", connected: false,
    });
    await openAddModal();
    fireEvent.change(jsonInput(), {
      target: { value: JSON.stringify({
        mcpServers: { exa: { type: "http", url: "https://mcp.exa.ai/mcp" } },
      }) },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add server" }).at(-1)!);
    await act(async () => {});
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ transport: "http" }),
    );
    expect(create.mock.calls[0][0]).not.toHaveProperty("type");
  });
});
