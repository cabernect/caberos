import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plug, Plus, Trash2, RefreshCw, ChevronDown, ChevronRight, Key, Search, Store, AlertTriangle } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { openUrl } from "@/lib/openUrl";
import type { McpServerInfo, McpToolInfo, McpCatalogEntry } from "@/lib/types";

type Tab = "mine" | "browse";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function Mcps() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [tools, setTools] = useState<Record<string, McpToolInfo[]>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [tab, setTab] = useState<Tab>("mine");
  const navigate = useNavigate();
  const { confirm } = useConfirm();

  const fetchServers = useCallback(async () => {
    try {
      const list = await api.listMcpServers();
      setServers(list);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") navigate("/settings");
    if (page === "vault") navigate("/vault");
    if (page === "skills") navigate("/skills");
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") return;
    if (page === "channels") navigate("/channels");
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  const toggleExpand = async (serverId: string) => {
    const next = new Set(expanded);
    if (next.has(serverId)) {
      next.delete(serverId);
    } else {
      next.add(serverId);
      if (!tools[serverId]) {
        try {
          const t = await api.listMcpServerTools(serverId);
          setTools((prev) => ({ ...prev, [serverId]: t }));
        } catch {
          // ignore
        }
      }
    }
    setExpanded(next);
  };

  const handleDelete = async (serverId: string, serverName: string) => {
    const ok = await confirm({
      title: "Remove server?",
      message: `Remove "${serverName}"? This disconnects the server, unregisters its tools, and deletes all credentials.`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteMcpServer(serverId);
      fetchServers();
    } catch {
      // ignore
    }
  };

  const handleConnect = async (serverId: string) => {
    try {
      await api.connectMcpServer(serverId);
      await fetchServers();
    } catch {
      // ignore
    }
  };

  const handleApprovalChange = async (serverId: string, requireApproval: boolean) => {
    try {
      await api.updateMcpServer(serverId, { require_approval: requireApproval });
      fetchServers();
    } catch {
      // ignore
    }
  };

  const handleEnabledChange = async (serverId: string, enabled: boolean) => {
    try {
      await api.updateMcpServer(serverId, { enabled });
      fetchServers();
    } catch {
      // ignore
    }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="mcps"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="px-8 py-5"
          style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
        >
          <div className="flex items-center gap-2">
            <Plug className="h-5 w-5" style={{ color: "var(--accent)" }} />
            <h1 className="text-[18px] font-semibold text-[var(--ink)]">MCP Servers</h1>
          </div>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
            Connect external services via Model Context Protocol
          </p>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-3xl">
            {/* Tab toggle */}
            <div className="mb-4 flex gap-1 border-b" style={{ borderColor: "#E0DFDC" }}>
              <TabButton active={tab === "mine"} onClick={() => setTab("mine")} icon={<Plug className="h-3.5 w-3.5" />}>
                My Servers
              </TabButton>
              <TabButton active={tab === "browse"} onClick={() => setTab("browse")} icon={<Store className="h-3.5 w-3.5" />}>
                Browse Catalog
              </TabButton>
            </div>

            {tab === "mine" ? (
              <>
                {/* Add button */}
                <div className="mb-4 flex justify-end">
                  <button
                    onClick={() => setShowAdd(!showAdd)}
                    className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] font-medium transition"
                    style={{
                      background: showAdd ? "var(--surface)" : "var(--accent)",
                      color: showAdd ? "var(--ink)" : "#fff",
                      border: "1px solid var(--border)",
                      cursor: "pointer",
                    }}
                  >
                    <Plus className="h-4 w-4" />
                    {showAdd ? "Cancel" : "Add Server"}
                  </button>
                </div>

                {/* Add form */}
                {showAdd && (
                  <AddServerForm
                    onAdded={() => {
                      setShowAdd(false);
                      fetchServers();
                    }}
                  />
                )}

                {/* Server list */}
                {loading ? (
                  <div className="flex h-32 items-center justify-center">
                    <p className="text-[14px] text-[var(--ink-3)]">Loading…</p>
                  </div>
                ) : servers.length === 0 ? (
                  <div className="flex h-64 flex-col items-center justify-center">
                    <Plug className="h-12 w-12" style={{ color: "var(--ink-3)" }} />
                    <p className="mt-4 text-[14px] text-[var(--ink-2)]">No MCP servers configured</p>
                    <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                      Browse the catalog or add a server manually
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {servers.map((server) => (
                      <ServerCard
                        key={server.id}
                        server={server}
                        expanded={expanded.has(server.id)}
                        tools={tools[server.id]}
                        onToggle={() => toggleExpand(server.id)}
                        onDelete={() => handleDelete(server.id, server.name)}
                        onConnect={() => handleConnect(server.id)}
                        onApprovalChange={(requireApproval) => handleApprovalChange(server.id, requireApproval)}
                        onEnabledChange={(enabled) => handleEnabledChange(server.id, enabled)}
                        onCredentialChanged={fetchServers}
                      />
                    ))}
                  </div>
                )}
              </>
            ) : (
              <CatalogBrowser
                installedNames={new Set(servers.map((s) => s.name))}
                onInstalled={async () => {
                  await fetchServers();
                  setTab("mine");
                }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function AddServerForm({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<"form" | "json">("form");
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [envTemplate, setEnvTemplate] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      const data: Record<string, unknown> = {
        name,
        transport,
        enabled: true,
      };
      if (transport === "stdio") {
        data.command = command;
        if (args.trim()) data.args = args.split(/\s+/).filter(Boolean);
      } else {
        data.url = url;
      }
      if (envTemplate.trim()) {
        try {
          data.env_template = JSON.parse(envTemplate);
        } catch {
          setError("Env template must be valid JSON");
          setAdding(false);
          return;
        }
      }
      await api.createMcpServer(data as Parameters<typeof api.createMcpServer>[0]);
      onAdded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add server");
    } finally {
      setAdding(false);
    }
  };

  const handleJsonSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      const parsed = JSON.parse(jsonText);
      // Support two JSON formats:
      // 1. CaberOS format: { name, transport, command, args, url, ... }
      // 2. Claude Desktop format: { "mcpServers": { "name": { "command": ..., "args": [...] } } }
      //    or just { "name": { "command": ..., "args": [...] } }
      let data: Record<string, unknown>;

      if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
        // Claude Desktop config — take the first server
        const entries = Object.entries(parsed.mcpServers);
        if (entries.length === 0) {
          setError("No servers found in mcpServers object");
          setAdding(false);
          return;
        }
        const [serverName, rawConfig] = entries[0];
        if (!isRecord(rawConfig)) {
          setError("MCP server configuration must be an object");
          setAdding(false);
          return;
        }
        data = { name: serverName, enabled: true, ...rawConfig };
        if (!data.transport) {
          data.transport = rawConfig.url ? "http" : "stdio";
        }
      } else if (parsed.command || parsed.url) {
        // Direct CaberOS format
        data = { enabled: true, ...parsed };
        if (!data.transport) {
          data.transport = parsed.url ? "http" : "stdio";
        }
        if (!data.name) {
          setError("JSON must include a \"name\" field");
          setAdding(false);
          return;
        }
      } else {
        // Maybe it's a single { "name": { config } } object
        const entries = Object.entries(parsed);
        if (entries.length === 1 && isRecord(entries[0][1])) {
          const [serverName, serverConfig] = entries[0];
          data = { name: serverName, enabled: true, ...serverConfig };
          if (!data.transport) {
            data.transport = serverConfig.url ? "http" : "stdio";
          }
        } else {
          setError("Unrecognized JSON format. Use CaberOS format ({ name, command, args }) or Claude Desktop format ({ mcpServers: { ... } })");
          setAdding(false);
          return;
        }
      }

      await api.createMcpServer(data as Parameters<typeof api.createMcpServer>[0]);
      onAdded();
    } catch (e) {
      if (e instanceof SyntaxError) {
        setError("Invalid JSON: " + e.message);
      } else {
        setError(e instanceof Error ? e.message : "Failed to add server");
      }
    } finally {
      setAdding(false);
    }
  };

  return (
    <div
      className="mb-4 rounded-[8px] border p-4"
      style={{ borderColor: "var(--border)", background: "var(--white)" }}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">Add MCP Server</h3>
        {/* Mode toggle */}
        <div className="flex gap-1 rounded-[5px] p-0.5" style={{ background: "var(--surface)" }}>
          <button
            type="button"
            onClick={() => { setMode("form"); setError(null); }}
            className="rounded-[4px] px-2.5 py-1 text-[11px] font-mono transition"
            style={{
              background: mode === "form" ? "var(--white)" : "none",
              color: mode === "form" ? "var(--ink)" : "var(--ink-3)",
              border: "none",
              cursor: "pointer",
            }}
          >
            Form
          </button>
          <button
            type="button"
            onClick={() => { setMode("json"); setError(null); }}
            className="rounded-[4px] px-2.5 py-1 text-[11px] font-mono transition"
            style={{
              background: mode === "json" ? "var(--white)" : "none",
              color: mode === "json" ? "var(--ink)" : "var(--ink-3)",
              border: "none",
              cursor: "pointer",
            }}
          >
            JSON
          </button>
        </div>
      </div>

      {mode === "form" ? (
        <form onSubmit={handleSubmit}>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Outlook"
                required
                className="w-full rounded-[5px] border px-3 py-2 text-[13px]"
                style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Transport</label>
              <select
                value={transport}
                onChange={(e) => setTransport(e.target.value)}
                className="w-full rounded-[5px] border px-3 py-2 text-[13px]"
                style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
              >
                <option value="stdio">stdio (local process)</option>
                <option value="http">http (remote server)</option>
              </select>
            </div>
            {transport === "stdio" ? (
              <>
                <div>
                  <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Command</label>
                  <input
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    placeholder="e.g. uvx outlook-graph-mcp"
                    required
                    className="w-full rounded-[5px] border px-3 py-2 font-mono text-[13px]"
                    style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
                  />
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Arguments (space-separated)</label>
                  <input
                    value={args}
                    onChange={(e) => setArgs(e.target.value)}
                    placeholder="e.g. --port 3000"
                    className="w-full rounded-[5px] border px-3 py-2 font-mono text-[13px]"
                    style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
                  />
                </div>
              </>
            ) : (
              <div>
                <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">URL</label>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://mcp-server.example.com"
                  required
                  className="w-full rounded-[5px] border px-3 py-2 font-mono text-[13px]"
                  style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
                />
              </div>
            )}
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Env template (JSON, optional)
              </label>
              <textarea
                value={envTemplate}
                onChange={(e) => setEnvTemplate(e.target.value)}
                placeholder='{"API_KEY": "{{credential_value}}"}'
                rows={2}
                className="w-full rounded-[5px] border px-3 py-2 font-mono text-[12px]"
                style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            {error && (
              <p className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
            )}
            <button
              type="submit"
              disabled={adding}
              className="rounded-[6px] px-4 py-2 text-[13px] font-medium transition"
              style={{
                background: adding ? "var(--surface)" : "var(--accent)",
                color: adding ? "var(--ink-3)" : "#fff",
                cursor: adding ? "not-allowed" : "pointer",
                border: "none",
              }}
            >
              {adding ? "Adding…" : "Add Server"}
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleJsonSubmit}>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Server config (JSON)
              </label>
              <p className="mb-2 text-[11px] text-[var(--ink-3)]">
                Paste a CaberOS config or Claude Desktop config. Examples:
              </p>
              <pre
                className="mb-2 rounded-[4px] p-2 font-mono text-[10px] overflow-x-auto"
                style={{ background: "var(--surface)", color: "var(--ink-3)" }}
              >
{`// CaberOS format:
{
  "name": "my-server",
  "transport": "stdio",
  "command": "uvx",
  "args": ["my-mcp-server"],
  "env_template": { "API_KEY": "{{credential_value}}" }
}

// Claude Desktop format:
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-mcp-server"]
    }
  }
}`}
              </pre>
              <textarea
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                placeholder='{\n  "name": "my-server",\n  "command": "uvx",\n  "args": ["my-mcp-server"]\n}'
                rows={10}
                required
                className="w-full rounded-[5px] border px-3 py-2 font-mono text-[12px]"
                style={{ borderColor: "#E0DFDC", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            {error && (
              <p className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
            )}
            <button
              type="submit"
              disabled={adding}
              className="rounded-[6px] px-4 py-2 text-[13px] font-medium transition"
              style={{
                background: adding ? "var(--surface)" : "var(--accent)",
                color: adding ? "var(--ink-3)" : "#fff",
                cursor: adding ? "not-allowed" : "pointer",
                border: "none",
              }}
            >
              {adding ? "Adding…" : "Add Server"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function ServerCard({
  server,
  expanded,
  tools,
  onToggle,
  onDelete,
  onConnect,
  onApprovalChange,
  onEnabledChange,
  onCredentialChanged,
}: {
  server: McpServerInfo;
  expanded: boolean;
  tools?: McpToolInfo[];
  onToggle: () => void;
  onDelete: () => void;
  onConnect: () => Promise<void>;
  onApprovalChange: (requireApproval: boolean) => void;
  onEnabledChange: (enabled: boolean) => void;
  onCredentialChanged: () => void;
}) {
  const statusColor = server.connected ? "#6A8216" : "#999";
  const statusText = server.connected ? "connected" : server.enabled ? "disconnected" : "disabled";
  const needsApiKey = server.auth_type === "api_key" && !server.connected && server.enabled;
  const needsOAuth = server.auth_type === "oauth" && !server.connected && server.enabled;
  const [showCredForm, setShowCredForm] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const { toast } = useConfirm();

  return (
    <div
      className="rounded-[8px] border"
      style={{ borderColor: "#E0DFDC", background: "var(--white)" }}
    >
      {/* Header row */}
      <div className="flex items-center gap-3 p-4">
        <button
          onClick={onToggle}
          className="rounded-[4px] p-0.5 transition"
          style={{ background: "none", border: "none", cursor: "pointer" }}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" style={{ color: "var(--ink-2)" }} />
          ) : (
            <ChevronRight className="h-4 w-4" style={{ color: "var(--ink-2)" }} />
          )}
        </button>
        <div className="flex-1">
          <span className="text-[14px] font-medium" style={{ color: "var(--ink)" }}>
            {server.name}
          </span>
          <span
            className="ml-2 font-mono text-[10px] uppercase tracking-wider"
            style={{ color: "var(--ink-3)" }}
          >
            {server.transport}
          </span>
        </div>
        {/* Enable/disable toggle */}
        <button
          onClick={() => onEnabledChange(!server.enabled)}
          className="relative inline-flex h-4 w-7 items-center rounded-full transition"
          style={{
            background: server.enabled ? "var(--accent)" : "#D1D1D1",
            border: "none",
            cursor: "pointer",
          }}
          title={server.enabled ? "Disable server" : "Enable server"}
        >
          <span
            className="inline-block h-3 w-3 rounded-full bg-white transition"
            style={{ transform: server.enabled ? "translateX(14px)" : "translateX(2px)" }}
          />
        </button>
        <span
          className="flex items-center gap-1 font-mono text-[11px]"
          style={{ color: statusColor }}
        >
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: statusColor }}
          />
          {statusText}
        </span>
        <span className="font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {server.tool_count} tools
        </span>
        {/* Actions */}
        {needsApiKey && (
          <button
            onClick={() => {
              setShowCredForm(!showCredForm);
              if (!expanded) onToggle();
            }}
            className="flex items-center gap-1 rounded-[4px] px-2 py-1 text-[11px] font-medium transition"
            style={{
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              cursor: "pointer",
            }}
            title="Configure API key"
          >
            <Key className="h-3 w-3" />
            Set Key
          </button>
        )}
        {needsOAuth && (
          <button
            onClick={async () => {
              setOauthLoading(true);
              try {
                const { authorize_url } = await api.startMcpOAuth(server.id);
                // Open the authorize URL in a new tab
                openUrl(authorize_url);
                // Start polling for OAuth completion
                const poll = setInterval(async () => {
                  try {
                    const status = await api.getMcpOAuthStatus(server.id);
                    if (status.status === "completed") {
                      clearInterval(poll);
                      setOauthLoading(false);
                      onCredentialChanged();
                    } else if (status.status === "error") {
                      clearInterval(poll);
                      setOauthLoading(false);
                      toast(`OAuth failed: ${status.error}`);
                    } else if (status.status === "none") {
                      // Flow ended — check if we're connected now
                      clearInterval(poll);
                      setOauthLoading(false);
                      onCredentialChanged();
                    }
                  } catch {
                    // ignore poll errors
                  }
                }, 2000);
                // Stop polling after 5 minutes (matches backend timeout)
                const timeout = setTimeout(() => {
                  clearInterval(poll);
                  setOauthLoading(false);
                  toast("OAuth timed out — you didn't complete the authorization in 5 minutes. Click 'Connect OAuth' to try again.");
                }, 300000);
                // Store cleanup function so the cancel button can stop polling
                (window as any)._oauthCleanup = () => {
                  clearInterval(poll);
                  clearTimeout(timeout);
                  setOauthLoading(false);
                };
              } catch (e) {
                setOauthLoading(false);
                toast(e instanceof Error ? e.message : "Failed to start OAuth flow");
              }
            }}
            disabled={oauthLoading}
            className="flex items-center gap-1 rounded-[4px] px-2 py-1 text-[11px] font-medium transition"
            style={{
              background: oauthLoading ? "var(--surface)" : "var(--accent)",
              color: oauthLoading ? "var(--ink-3)" : "#fff",
              border: "none",
              cursor: oauthLoading ? "not-allowed" : "pointer",
            }}
            title="Connect with OAuth"
          >
            <Key className="h-3 w-3" />
            {oauthLoading ? (
              <>
                <span>Waiting…</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if ((window as any)._oauthCleanup) (window as any)._oauthCleanup();
                  }}
                  className="ml-1 text-[10px] underline"
                  style={{ color: "var(--danger)" }}
                >
                  Cancel
                </button>
              </>
            ) : (
              "Connect OAuth"
            )}
          </button>
        )}
        {server.enabled && (
          <button
            onClick={async () => {
              setConnecting(true);
              try {
                await onConnect();
              } finally {
                setConnecting(false);
              }
            }}
            disabled={connecting}
            className="rounded-[4px] p-1 transition"
            style={{ background: "none", border: "1px solid #E0DFDC", cursor: connecting ? "not-allowed" : "pointer" }}
            title="Reconnect"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${connecting ? "animate-spin" : ""}`}
              style={{ color: "var(--ink-2)" }}
            />
          </button>
        )}
        <button
          onClick={onDelete}
          className="rounded-[4px] p-1 transition"
          style={{ background: "none", border: "1px solid #E0DFDC", cursor: "pointer" }}
          title="Remove"
        >
          <Trash2 className="h-3.5 w-3.5" style={{ color: "var(--danger)" }} />
        </button>
      </div>

      {/* Connection error alert */}
      {server.connect_error && !server.connected && server.enabled && (
        <div
          className="flex items-center gap-2 px-4 py-2"
          style={{
            background: "rgba(239,68,68,0.05)",
            borderTop: "1px solid rgba(239,68,68,0.15)",
            borderBottom: "1px solid rgba(239,68,68,0.15)",
          }}
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--danger)" }} />
          <span className="flex-1 text-[12px]" style={{ color: "var(--danger)" }}>
            {server.connect_error}
          </span>
          {needsOAuth && (
            <button
              onClick={async () => {
                setOauthLoading(true);
                try {
                  const { authorize_url } = await api.startMcpOAuth(server.id);
                  if (authorize_url) openUrl(authorize_url);
                } catch (e) {
                  setOauthLoading(false);
                  toast(e instanceof Error ? e.message : "Failed to start OAuth flow");
                }
              }}
              disabled={oauthLoading}
              className="flex items-center gap-1 rounded-[4px] px-2 py-1 text-[11px] font-medium transition"
              style={{
                background: "var(--danger)",
                color: "#fff",
                border: "none",
                cursor: oauthLoading ? "not-allowed" : "pointer",
              }}
            >
              <Key className="h-3 w-3" />
              {oauthLoading ? "Waiting…" : "Re-authenticate"}
            </button>
          )}
          <button
            onClick={async () => {
              setConnecting(true);
              try {
                await onConnect();
              } finally {
                setConnecting(false);
              }
            }}
            disabled={connecting}
            className="flex items-center gap-1 rounded-[4px] px-2 py-1 text-[11px] font-medium transition"
            style={{
              background: "none",
              color: "var(--ink-2)",
              border: "1px solid var(--border)",
              cursor: connecting ? "not-allowed" : "pointer",
            }}
          >
            <RefreshCw className={`h-3 w-3 ${connecting ? "animate-spin" : ""}`} />
            Retry
          </button>
        </div>
      )}

      {/* Credential form (shown when user clicks "Set Key") */}
      {showCredForm && (
        <CredentialForm
          serverId={server.id}
          envTemplate={server.env_template}
          onSaved={() => {
            setShowCredForm(false);
            onCredentialChanged();
          }}
          onCancel={() => setShowCredForm(false)}
        />
      )}

      {/* Expanded — tools list */}
      {expanded && (
        <div className="border-t px-4 py-3" style={{ borderColor: "#E0DFDC" }}>
          {server.command && (
            <div className="mb-3">
              <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">Command</span>
              <p className="font-mono text-[12px]" style={{ color: "var(--ink-2)" }}>
                {server.command}
                {server.args && server.args.length > 0 ? " " + server.args.join(" ") : ""}
              </p>
            </div>
          )}
          {server.url && (
            <div className="mb-3">
              <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">URL</span>
              <p className="font-mono text-[12px]" style={{ color: "var(--ink-2)" }}>{server.url}</p>
            </div>
          )}

          {/* Approval toggle */}
          <div className="mb-3 flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
              Require approval
            </span>
            <button
              onClick={() => onApprovalChange(!server.require_approval)}
              className="relative inline-flex h-5 w-9 items-center rounded-full transition"
              style={{
                background: server.require_approval ? "var(--accent)" : "#D6D5D2",
                border: "none",
                cursor: "pointer",
              }}
              title={server.require_approval ? "Approval required — click to bypass" : "No approval needed — click to require"}
            >
              <span
                className="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition"
                style={{ transform: server.require_approval ? "translateX(18px)" : "translateX(2px)" }}
              />
            </button>
            <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
              {server.require_approval ? "Operator approves each call" : "Agent runs without asking"}
            </span>
          </div>

          {/* Tools */}
          <div>
            <span className="mb-2 block font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
              Tools ({tools?.length ?? 0})
            </span>
            {!tools ? (
              <p className="text-[12px] text-[var(--ink-3)]">Loading tools…</p>
            ) : tools.length === 0 ? (
              <p className="text-[12px] text-[var(--ink-3)]">
                No tools discovered. Make sure the server is connected.
              </p>
            ) : (
              <div className="space-y-1.5">
                {tools.map((tool) => (
                  <ToolRow key={tool.id} tool={tool} />
                ))}
              </div>
            )}
          </div>

          {/* Credentials section */}
          <CredentialManager
            serverId={server.id}
            hasCredentials={server.has_credentials}
            envTemplate={server.env_template}
            onChanged={onCredentialChanged}
          />
        </div>
      )}
    </div>
  );
}

function ToolRow({ tool }: { tool: McpToolInfo }) {
  const [expanded, setExpanded] = useState(false);
  const maxLen = 80;
  const isLong = tool.description.length > maxLen;
  const shortDesc = isLong ? tool.description.slice(0, maxLen) + "…" : tool.description;

  return (
    <div
      className="flex items-start gap-2 rounded-[5px] px-3 py-2"
      style={{ background: "var(--surface)" }}
    >
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[12px] font-medium" style={{ color: "var(--ink)" }}>
            {tool.capability_name}
          </span>
          {tool.require_approval && (
            <span
              className="rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase"
              style={{ background: "var(--surface)", color: "var(--ink-3)" }}
            >
              approval
            </span>
          )}
          {tool.egress && (
            <span
              className="rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase"
              style={{ background: "var(--surface)", color: "var(--ink-3)" }}
            >
              egress
            </span>
          )}
        </div>
        <p
          className="mt-0.5 text-[11px]"
          style={{ color: "var(--ink-2)", cursor: isLong ? "pointer" : "default" }}
          onClick={() => isLong && setExpanded(!expanded)}
        >
          {expanded ? tool.description : shortDesc}
          {isLong && (
            <span className="ml-1 font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>
              {expanded ? "[-]" : "[+]"}
            </span>
          )}
        </p>
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition"
      style={{
        borderColor: active ? "var(--accent)" : "transparent",
        color: active ? "var(--ink)" : "var(--ink-3)",
        background: "none",
        cursor: "pointer",
      }}
    >
      {icon}
      {children}
    </button>
  );
}

function CredentialForm({
  serverId,
  envTemplate,
  onSaved,
  onCancel,
}: {
  serverId: string;
  envTemplate: Record<string, string> | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Determine the env var name from the template (e.g. "API_KEY", "NOTION_TOKEN")
  const envVarName = envTemplate
    ? Object.keys(envTemplate).find((k) => envTemplate[k].includes("{{credential_value}}"))
    : null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.storeMcpCredential(serverId, {
        credential_type: "api_key",
        value: apiKey.trim(),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save credential");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="border-t px-4 py-3"
      style={{ borderColor: "#E0DFDC", background: "var(--surface)" }}
    >
      <form onSubmit={handleSave} className="space-y-2">
        <div className="flex items-center gap-2">
          <Key className="h-3.5 w-3.5" style={{ color: "var(--ink-3)" }} />
          <span className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
            Configure API Key
          </span>
          {envVarName && (
            <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--ink-3)" }}>
              {envVarName}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste your API key…"
            required
            autoFocus
            className="flex-1 rounded-[5px] border px-3 py-2 font-mono text-[12px]"
            style={{
              borderColor: "#E0DFDC",
              background: "var(--white)",
              color: "var(--ink)",
            }}
          />
          <button
            type="submit"
            disabled={saving}
            className="rounded-[5px] px-3 py-2 text-[12px] font-medium transition"
            style={{
              background: saving ? "var(--surface)" : "var(--accent)",
              color: saving ? "var(--ink-3)" : "#fff",
              border: "none",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "Saving…" : "Save & Connect"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-[5px] px-3 py-2 text-[12px] transition"
            style={{
              background: "none",
              color: "var(--ink-3)",
              border: "1px solid #E0DFDC",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </div>
        {error && (
          <p className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
        )}
      </form>
    </div>
  );
}

function CredentialManager({
  serverId,
  hasCredentials,
  envTemplate,
  onChanged,
}: {
  serverId: string;
  hasCredentials: boolean;
  envTemplate: Record<string, string> | null;
  onChanged: () => void;
}) {
  const [creds, setCreds] = useState<{ id: string; credential_type: string; label: string | null; created_at: string }[]>([]);
  const [showForm, setShowForm] = useState(false);
  const { confirm } = useConfirm();
  const envVarName = envTemplate
    ? Object.keys(envTemplate).find((k) => envTemplate[k].includes("{{credential_value}}"))
    : null;

  const fetchCreds = useCallback(async () => {
    try {
      const list = await api.listMcpCredentials(serverId);
      setCreds(list);
    } catch {
      // ignore
    }
  }, [serverId]);

  useEffect(() => {
    if (hasCredentials || showForm) {
      fetchCreds();
    }
  }, [hasCredentials, showForm, fetchCreds]);

  const handleDelete = async (credId: string) => {
    const ok = await confirm({
      title: "Delete credential?",
      message: "The server will need to be reconfigured to reconnect.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteMcpCredential(serverId, credId);
      fetchCreds();
      onChanged();
    } catch {
      // ignore
    }
  };

  if (!envTemplate && !hasCredentials) return null;

  return (
    <div className="mt-3 border-t pt-3" style={{ borderColor: "#E0DFDC" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key className="h-3.5 w-3.5" style={{ color: "var(--ink-3)" }} />
          <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
            Credentials
          </span>
          {envVarName && (
            <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>
              ({envVarName})
            </span>
          )}
        </div>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="text-[11px] font-medium transition"
            style={{
              background: "none",
              color: "var(--accent)",
              border: "none",
              cursor: "pointer",
            }}
          >
            {hasCredentials ? "Update key" : "Add key"}
          </button>
        )}
      </div>

      {/* Existing credentials list */}
      {creds.length > 0 && (
        <div className="mt-2 space-y-1">
          {creds.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-2 rounded-[5px] px-3 py-2"
              style={{ background: "var(--surface)" }}
            >
              <span className="font-mono text-[11px]" style={{ color: "var(--ink-2)" }}>
                {c.credential_type}
              </span>
              <span className="font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
                ••••••••
              </span>
              {c.label && (
                <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
                  {c.label}
                </span>
              )}
              <span className="ml-auto text-[10px]" style={{ color: "var(--ink-3)" }}>
                {new Date(c.created_at).toLocaleDateString()}
              </span>
              <button
                onClick={() => handleDelete(c.id)}
                className="rounded-[3px] p-0.5 transition"
                style={{ background: "none", border: "none", cursor: "pointer" }}
                title="Delete credential"
              >
                <Trash2 className="h-3 w-3" style={{ color: "var(--danger)" }} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Inline form */}
      {showForm && (
        <div className="mt-2">
          <CredentialForm
            serverId={serverId}
            envTemplate={envTemplate}
            onSaved={() => {
              setShowForm(false);
              fetchCreds();
              onChanged();
            }}
            onCancel={() => setShowForm(false)}
          />
        </div>
      )}

      {!hasCredentials && !showForm && envTemplate && (
        <p className="mt-1 text-[11px]" style={{ color: "var(--ink-3)" }}>
          No credential configured. Click "Add key" to set one up.
        </p>
      )}
    </div>
  );
}

const CATEGORY_LABELS: Record<string, string> = {
  search: "Search & Web",
  productivity: "Productivity",
  design: "Design",
  communication: "Communication",
  "dev-tools": "Developer Tools",
  databases: "Databases",
  devops: "DevOps & Infra",
  files: "File & Storage",
};

const AUTH_LABELS: Record<string, string> = {
  none: "No auth",
  api_key: "API key",
  oauth: "OAuth",
};

function CatalogBrowser({
  installedNames,
  onInstalled,
}: {
  installedNames: Set<string>;
  onInstalled: () => void;
}) {
  const [entries, setEntries] = useState<McpCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const fetchCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listMcpCatalog(category ?? undefined, search || undefined);
      setEntries(list);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [category, search]);

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  const handleInstall = async (name: string) => {
    setInstalling(name);
    setMessage(null);
    try {
      const result = await api.installFromCatalog(name);
      setMessage(result.message ?? `${name} installed.`);
      // Always refresh + switch to "My Servers" so the user sees the
      // newly installed server (even if it needs credentials to connect).
      onInstalled();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Install failed");
    } finally {
      setInstalling(null);
    }
  };

  const categories = [...new Set(entries.map((e) => e.category))];

  return (
    <div>
      {/* Search bar */}
      <div className="mb-4 flex gap-2">
        <div className="relative flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
            style={{ color: "var(--ink-3)" }}
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search MCP servers…"
            className="w-full rounded-[6px] border py-2 pl-9 pr-3 text-[13px]"
            style={{
              borderColor: "#E0DFDC",
              background: "var(--white)",
              color: "var(--ink)",
            }}
          />
        </div>
      </div>

      {/* Category filter */}
      {categories.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          <CategoryChip active={category === null} onClick={() => setCategory(null)}>
            All
          </CategoryChip>
          {categories.map((cat) => (
            <CategoryChip key={cat} active={category === cat} onClick={() => setCategory(cat)}>
              {CATEGORY_LABELS[cat] ?? cat}
            </CategoryChip>
          ))}
        </div>
      )}

      {/* Message */}
      {message && (
        <div
          className="mb-4 rounded-[6px] border px-3 py-2 text-[12px]"
          style={{
            borderColor: "#E0DFDC",
            background: "var(--surface)",
            color: "var(--ink-2)",
          }}
        >
          {message}
        </div>
      )}

      {/* Catalog grid */}
      {loading ? (
        <div className="flex h-32 items-center justify-center">
          <p className="text-[14px] text-[var(--ink-3)]">Loading catalog…</p>
        </div>
      ) : entries.length === 0 ? (
        <div className="flex h-32 items-center justify-center">
          <p className="text-[14px] text-[var(--ink-3)]">No servers found</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {entries.map((entry) => {
            const isInstalled = installedNames.has(entry.name);
            return (
              <div
                key={entry.name}
                className="flex flex-col rounded-[8px] border p-4"
                style={{
                  borderColor: "#E0DFDC",
                  background: "var(--white)",
                }}
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <span className="text-[14px] font-medium" style={{ color: "var(--ink)" }}>
                      {entry.name}
                    </span>
                    <span
                      className="ml-2 font-mono text-[9px] uppercase tracking-wider"
                      style={{ color: "var(--ink-3)" }}
                    >
                      {entry.vendor}
                    </span>
                  </div>
                  <span
                    className="rounded-full px-2 py-0.5 font-mono text-[9px] uppercase"
                    style={{
                      background: "var(--surface)",
                      color: entry.auth_type === "none" ? "#6A8216" : "var(--ink-3)",
                    }}
                  >
                    {AUTH_LABELS[entry.auth_type] ?? entry.auth_type}
                  </span>
                </div>

                {/* Description */}
                <p className="mt-1.5 flex-1 text-[12px]" style={{ color: "var(--ink-2)" }}>
                  {entry.description}
                </p>

                {/* Category + transport */}
                <div className="mt-2 flex items-center gap-2">
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {CATEGORY_LABELS[entry.category] ?? entry.category}
                  </span>
                  <span style={{ color: "var(--ink-3)" }}>·</span>
                  <span
                    className="font-mono text-[10px] uppercase tracking-wider"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {entry.transport}
                  </span>
                </div>

                {/* Install button */}
                <div className="mt-3">
                  {isInstalled ? (
                    <span
                      className="inline-block rounded-[5px] px-3 py-1.5 text-[12px] font-medium"
                      style={{
                        background: "var(--surface)",
                        color: "#6A8216",
                        border: "1px solid #D4E0A8",
                      }}
                    >
                      Installed
                    </span>
                  ) : (
                    <button
                      onClick={() => handleInstall(entry.name)}
                      disabled={installing === entry.name}
                      className="rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition"
                      style={{
                        background: installing === entry.name ? "var(--surface)" : "var(--accent)",
                        color: installing === entry.name ? "var(--ink-3)" : "#fff",
                        border: "none",
                        cursor: installing === entry.name ? "not-allowed" : "pointer",
                      }}
                    >
                      {installing === entry.name ? "Installing…" : "Install"}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CategoryChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="rounded-full px-2.5 py-1 text-[11px] font-medium transition"
      style={{
        background: active ? "var(--accent)" : "var(--surface)",
        color: active ? "#fff" : "var(--ink-2)",
        border: "1px solid #E0DFDC",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
