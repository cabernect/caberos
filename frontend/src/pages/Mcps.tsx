import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plug, Plus, Trash2, RefreshCw, Key, Search, Store, AlertTriangle, X, MoreHorizontal, Play } from "lucide-react";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
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
  const [showAdd, setShowAdd] = useState(false);
  const [tab, setTab] = useState<Tab>("mine");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [usedBy, setUsedBy] = useState<Record<string, string[]>>({});
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const navigate = useNavigate();
  const { confirm, toast } = useConfirm();

  const fetchServers = useCallback(async () => {
    try {
      const list = await api.listMcpServers();
      setServers(list);
      // Blast radius — which agents can reach each server's tools.
      for (const s of list) {
        api
          .getMcpServerBlastRadius(s.id)
          .then((b) =>
            setUsedBy((prev) => ({ ...prev, [s.id]: b.map((r) => r.agent_name) })),
          )
          .catch(() => {});
      }
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
    navigate(NAV_ROUTES[page]);
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
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not remove this MCP server.");
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
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--ground)" }}>
      <DashboardSidebar
        active="mcps"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Capabilities" }, { label: "MCPs" }]}
          title="MCP servers"
          subtitle="Connect external tools, and decide exactly what each one may do."
          actions={
            tab === "mine" ? (
              <Button onClick={() => setShowAdd(true)}>
                <Plus />
                Add server
              </Button>
            ) : undefined
          }
        />

        <div className="px-8 pt-4">
          <PageIntro def={INTRO_BY_KEY.mcps} />
        </div>

        {/* Filter row — pinned below the header */}
        <div className="px-8 pb-4">
          <div className="flex flex-wrap items-center gap-3">
            <FilterPills
              pills={[
                { key: "mine", label: "My servers", count: servers.length },
                { key: "browse", label: "Browse catalog" },
              ]}
              active={tab}
              onChange={(k) => setTab(k as Tab)}
              variant="segmented"
            />
            {(tab === "browse" || servers.length > 0) && (
              <div className="relative ml-auto w-[280px]">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={tab === "mine" ? "Search servers" : "Search catalog…"}
                  className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                />
              </div>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-8 pb-6">
          {tab === "mine" ? (
            loading ? (
              <p className="py-20 text-center text-[14px] text-ink-faint">Loading…</p>
            ) : servers.length === 0 ? (
              <div className="mx-auto max-w-3xl">
                <EmptyState
                  icon={Plug}
                  title="No MCP servers configured"
                  action={
                    <Button variant="secondary" onClick={() => setTab("browse")}>
                      <Store />Browse catalog
                    </Button>
                  }
                >
                  Browse the catalog or add a server manually.
                </EmptyState>
              </div>
            ) : (
              (() => {
                const q = search.trim().toLowerCase();
                const visible = q
                  ? servers.filter((s) => s.name.toLowerCase().includes(q))
                  : servers;
                const connected = visible.filter((s) => s.connected);
                const other = visible.filter((s) => !s.connected);
                const selected =
                  servers.find((s) => s.id === selectedId) ??
                  connected[0] ??
                  visible[0] ??
                  null;
                if (visible.length === 0)
                  return (
                    <p className="py-12 text-center text-[13px] text-ink-faint">
                      No servers match “{search}”.
                    </p>
                  );
                const renderCard = (server: McpServerInfo) => (
                  <ServerRow
                    key={server.id}
                    server={server}
                    selected={selected?.id === server.id}
                    usedBy={usedBy[server.id]}
                    menuOpen={menuFor === server.id}
                    onSelect={() => setSelectedId(server.id)}
                    onMenu={(open) => setMenuFor(open ? server.id : null)}
                    onDelete={() => {
                      setMenuFor(null);
                      handleDelete(server.id, server.name);
                    }}
                    onEnabledChange={(enabled) => handleEnabledChange(server.id, enabled)}
                  />
                );
                return (
                  <div className="flex items-start gap-6">
                    <div className="min-w-0 flex-1">
                      {connected.length > 0 && (
                        <>
                          <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                            Connected · {connected.length}
                          </p>
                          <div className="mb-5 space-y-2.5">{connected.map(renderCard)}</div>
                        </>
                      )}
                      {other.length > 0 && (
                        <>
                          <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                            Available · {other.length}
                          </p>
                          <div className="space-y-2.5">{other.map(renderCard)}</div>
                        </>
                      )}
                    </div>
                    {selected && (
                      <ServerDetail
                        key={selected.id}
                        server={selected}
                        usedBy={usedBy[selected.id]}
                        onDelete={() => handleDelete(selected.id, selected.name)}
                        onChanged={fetchServers}
                      />
                    )}
                  </div>
                );
              })()
            )
          ) : (
            <CatalogBrowser
              search={search}
              installedNames={new Set(servers.map((s) => s.name))}
              onInstalled={async () => {
                setSearch("");
                await fetchServers();
                setTab("mine");
              }}
            />
          )}
        </div>
      </div>

      <AddServerModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onAdded={() => {
          setShowAdd(false);
          fetchServers();
        }}
      />
    </div>
  );
}

function AddServerModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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
      // 2. Standard mcpServers format: { "mcpServers": { "name": { "command": ..., "args": [...] } } }
      //    or just { "name": { "command": ..., "args": [...] } }
      let data: Record<string, unknown>;

      if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
        // Standard mcpServers config — take the first server
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
          setError("Unrecognized JSON format. Use CaberOS format ({ name, command, args }) or standard format ({ mcpServers: { ... } })");
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

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/25"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Add MCP server</h2>
            <p className="mt-0.5 text-[12px] text-ink-3">
              Fill the form, or paste a CaberOS / standard JSON config.
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Mode toggle */}
        <div className="px-5 pt-4">
          <FilterPills
            pills={[
              { key: "form", label: "Form" },
              { key: "json", label: "Paste JSON" },
            ]}
            active={mode}
            onChange={(k) => {
              setMode(k as "form" | "json");
              setError(null);
            }}
            variant="segmented"
          />
        </div>

        <div className="max-h-[55vh] overflow-y-auto p-5">
          {mode === "form" ? (
        <form id="mcp-add-form" onSubmit={handleSubmit}>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Outlook"
                required
                className="w-full rounded-[5px] border px-3 py-2 text-[13px]"
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Transport</label>
              <Select
                value={transport}
                onChange={setTransport}
                options={[
                  { value: "stdio", label: "stdio (local process)" },
                  { value: "http", label: "http (remote server)" },
                ]}
                className="w-full rounded-[5px] border border-[var(--border)] bg-surface px-3 py-2 text-[13px] text-ink"
                align="left" panelClassName="text-[13px]"
              />
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
                    style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
                  />
                </div>
                <div>
                  <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">Arguments (space-separated)</label>
                  <input
                    value={args}
                    onChange={(e) => setArgs(e.target.value)}
                    placeholder="e.g. --port 3000"
                    className="w-full rounded-[5px] border px-3 py-2 font-mono text-[13px]"
                    style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
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
                  style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
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
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            {error && (
              <p className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
            )}
          </div>
        </form>
          ) : (
        <form id="mcp-add-json" onSubmit={handleJsonSubmit}>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Server config (JSON)
              </label>
              <p className="mb-2 text-[11px] text-[var(--ink-3)]">
                Paste a CaberOS config or standard MCP config. Examples:
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

// Standard format:
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
                style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              />
            </div>
            {error && (
              <p className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</p>
            )}
          </div>
        </form>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3.5">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            type="submit"
            form={mode === "form" ? "mcp-add-form" : "mcp-add-json"}
            disabled={adding}
          >
            {adding ? "Adding…" : "Add server"}
          </Button>
        </div>
      </div>
    </div>
  );
}

type Perm = "allow" | "ask" | "block";

function ServerRow({
  server,
  selected,
  usedBy,
  menuOpen,
  onSelect,
  onMenu,
  onDelete,
  onEnabledChange,
}: {
  server: McpServerInfo;
  selected: boolean;
  usedBy?: string[];
  menuOpen: boolean;
  onSelect: () => void;
  onMenu: (open: boolean) => void;
  onDelete: () => void;
  onEnabledChange: (enabled: boolean) => void;
}) {
  const subtitle =
    usedBy && usedBy.length > 0
      ? `Used by ${usedBy.join(", ")}`
      : !server.enabled
        ? "Not enabled"
        : !server.connected && server.auth_type === "api_key"
          ? "Needs an API key to connect"
          : !server.connected && server.auth_type === "oauth"
            ? "Sign in to sync tools"
            : server.connected
              ? "No agents use this yet"
              : "Not connected";
  return (
    <div
      onClick={onSelect}
      className={`relative flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${
        selected ? "border-accent bg-surface" : "border-line bg-surface hover:border-ink-faint"
      }`}
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-accent-tint text-[15px] font-semibold text-accent">
        {server.name.charAt(0).toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-[14px] font-medium text-ink">{server.name}</span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
            {server.transport}
          </span>
        </div>
        <p className="mt-0.5 truncate text-[12px] text-ink-muted">{subtitle}</p>
      </div>
      <div className="hidden shrink-0 text-right md:block">
        <p className="font-mono text-[11px] text-ink-muted">
          {server.tool_filter === null
            ? `${server.tool_count} tools`
            : `${server.tool_filter.length} of ${server.tool_count} tools`}
        </p>
        <p
          className={`mt-0.5 flex items-center justify-end gap-1 font-mono text-[11px] ${
            server.connected ? "text-accent" : "text-ink-faint"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${server.connected ? "bg-accent" : "bg-ink-faint"}`}
          />
          {server.connected ? "healthy" : "not connected"}
        </p>
      </div>
      <Toggle
        checked={server.enabled}
        onCheckedChange={onEnabledChange}
        size="sm"
        aria-label={server.enabled ? "Disable server" : "Enable server"}
        title={server.enabled ? "Disable server" : "Enable server"}
      />
      <button
        onClick={(e) => {
          e.stopPropagation();
          onMenu(!menuOpen);
        }}
        className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
        title="Server actions"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {menuOpen && (
        <>
          <div
            className="fixed inset-0 z-10 cursor-default"
            onClick={(e) => {
              e.stopPropagation();
              onMenu(false);
            }}
          />
          <div className="absolute right-3 top-full z-20 mt-1 min-w-[140px] overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-lg">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-[12px] font-medium text-danger transition-colors hover:bg-sunken"
            >
              <Trash2 className="h-3.5 w-3.5" /> Remove
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function ServerDetail({
  server,
  usedBy,
  onDelete,
  onChanged,
}: {
  server: McpServerInfo;
  usedBy?: string[];
  onDelete: () => void;
  onChanged: () => void;
}) {
  const [tools, setTools] = useState<McpToolInfo[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showCredForm, setShowCredForm] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const { toast } = useConfirm();

  useEffect(() => {
    let live = true;
    api
      .listMcpServerTools(server.id)
      .then((t) => {
        if (live) setTools(t);
      })
      .catch(() => {
        if (live) setTools([]);
      });
    return () => {
      live = false;
    };
  }, [server.id]);

  const needsApiKey = server.auth_type === "api_key" && !server.connected && server.enabled;
  const needsOAuth = server.auth_type === "oauth" && !server.connected && server.enabled;
  const inFilter = (t: McpToolInfo) =>
    server.tool_filter === null || server.tool_filter.includes(t.tool_name);
  const permOf = (t: McpToolInfo): Perm =>
    !inFilter(t) ? "block" : t.require_approval ? "ask" : "allow";

  const setPerm = async (tool: McpToolInfo, perm: Perm) => {
    try {
      const allNames = (tools ?? []).map((t) => t.tool_name);
      const current = new Set(server.tool_filter ?? allNames);
      if (perm === "block") {
        current.delete(tool.tool_name);
        await api.updateMcpServer(server.id, {
          tool_filter: allNames.filter((n) => current.has(n)),
        });
      } else {
        current.add(tool.tool_name);
        const next = allNames.every((n) => current.has(n))
          ? null
          : allNames.filter((n) => current.has(n));
        await api.updateMcpServer(server.id, { tool_filter: next });
        const res = await api.updateMcpTool(server.id, tool.id, {
          require_approval: perm === "ask",
        });
        setTools((prev) =>
          prev
            ? prev.map((t) =>
                t.id === tool.id ? { ...t, require_approval: res.require_approval } : t,
              )
            : prev,
        );
      }
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update tool permission.");
    }
  };

  const setNewToolDefault = async (ask: boolean) => {
    try {
      await api.updateMcpServer(server.id, { require_approval: ask });
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update the default.");
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      await api.connectMcpServer(server.id);
      onChanged();
      toast("Reconnected — handshake completed.");
    } catch (e) {
      onChanged();
      toast(e instanceof Error ? e.message : "Connection failed.");
    } finally {
      setTesting(false);
    }
  };

  const startOAuth = async () => {
    setOauthLoading(true);
    try {
      const { authorize_url } = await api.startMcpOAuth(server.id);
      if (authorize_url) await openUrl(authorize_url);
      const poll = setInterval(async () => {
        try {
          const status = await api.getMcpOAuthStatus(server.id);
          if (status.status === "completed" || status.status === "none") {
            clearInterval(poll);
            setOauthLoading(false);
            onChanged();
          } else if (status.status === "error") {
            clearInterval(poll);
            setOauthLoading(false);
            toast(`OAuth failed: ${status.error}`);
          }
        } catch {
          // ignore poll errors
        }
      }, 2000);
      const timeout = setTimeout(() => {
        clearInterval(poll);
        setOauthLoading(false);
        toast("OAuth timed out — authorization wasn't completed in 5 minutes.");
      }, 300000);
      (window as any)._oauthCleanup = () => {
        clearInterval(poll);
        clearTimeout(timeout);
        setOauthLoading(false);
      };
    } catch (e) {
      setOauthLoading(false);
      toast(e instanceof Error ? e.message : "Failed to start OAuth flow");
    }
  };

  const statusText = server.connected
    ? "connected"
    : server.enabled
      ? "not connected"
      : "disabled";
  const shownTools = tools ? (showAll ? tools : tools.slice(0, 6)) : null;

  return (
    <div className="sticky top-0 w-[380px] shrink-0 rounded-xl border border-line bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold text-ink">{server.name}</h3>
          <p className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
            {server.transport}
          </p>
        </div>
        {server.enabled && (
          <Button variant="outline" size="sm" onClick={handleTest} disabled={testing}>
            <Play className="h-3.5 w-3.5" />
            {testing ? "Testing…" : "Test"}
          </Button>
        )}
      </div>

      <div className="max-h-[calc(100vh-300px)] overflow-y-auto px-4 py-3">
        {/* Status */}
        <p className="flex items-center gap-1.5 text-[12px] text-ink-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${server.connected ? "bg-accent" : "bg-ink-faint"}`}
          />
          {statusText} · {server.tool_count} tools
        </p>
        <p className="mt-1 text-[12px] text-ink-muted">
          {usedBy && usedBy.length > 0
            ? `Used by ${usedBy.join(", ")}`
            : "No agents use this yet"}
        </p>
        {server.command && (
          <p className="mt-1 truncate font-mono text-[11px] text-ink-faint" title={`${server.command} ${(server.args ?? []).join(" ")}`}>
            {server.command}
            {server.args && server.args.length > 0 ? " " + server.args.join(" ") : ""}
          </p>
        )}
        {server.url && (
          <p className="mt-1 truncate font-mono text-[11px] text-ink-faint" title={server.url}>
            {server.url}
          </p>
        )}

        {/* Connection error */}
        {server.connect_error && !server.connected && server.enabled && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-danger/20 bg-danger-tint px-3 py-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-danger" />
            <span className="flex-1 text-[12px] text-danger">{server.connect_error}</span>
            <button
              onClick={handleTest}
              disabled={testing}
              className="flex items-center gap-1 rounded border border-line bg-transparent px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-sunken disabled:cursor-not-allowed"
            >
              <RefreshCw className={`h-3 w-3 ${testing ? "animate-spin" : ""}`} />
              Retry
            </button>
          </div>
        )}

        {/* Auth actions */}
        {(needsApiKey || needsOAuth) && (
          <div className="mt-3">
            {needsApiKey && !showCredForm && (
              <button
                onClick={() => setShowCredForm(true)}
                className="flex cursor-pointer items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90"
              >
                <Key className="h-3.5 w-3.5" /> Set API key
              </button>
            )}
            {needsOAuth &&
              (oauthLoading ? (
                <span className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-muted">
                  <Key className="h-3.5 w-3.5" /> Waiting for sign-in…
                  <button
                    onClick={() => (window as any)._oauthCleanup?.()}
                    className="ml-1 cursor-pointer border-none bg-transparent text-[11px] text-danger underline"
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  onClick={startOAuth}
                  className="flex cursor-pointer items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90"
                >
                  <Key className="h-3.5 w-3.5" /> Connect OAuth
                </button>
              ))}
          </div>
        )}
        {showCredForm && needsApiKey && (
          <div className="mt-3 overflow-hidden rounded-md border border-line">
            <CredentialForm
              serverId={server.id}
              envTemplate={server.env_template}
              onSaved={() => {
                setShowCredForm(false);
                onChanged();
              }}
              onCancel={() => setShowCredForm(false)}
            />
          </div>
        )}
        <div className="mt-3">
          <CredentialManager
            serverId={server.id}
            hasCredentials={server.has_credentials}
            envTemplate={server.env_template}
            onChanged={onChanged}
          />
        </div>

        {/* Tool permissions */}
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <p className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
              Tool permissions
            </p>
            <Select
              value={server.require_approval ? "ask" : "allow"}
              onChange={(v) => setNewToolDefault(v === "ask")}
              options={[
                { value: "allow", label: "future tools: allow" },
                { value: "ask", label: "future tools: ask" },
              ]}
              title="The starting permission for tools this server discovers later"
              className="cursor-pointer rounded-md border border-line bg-surface px-1.5 py-0.5 text-[10px] font-medium text-ink-muted focus:border-accent focus:outline-none"
              panelClassName="text-[11px]"
            />
          </div>
          <p className="mt-0.5 text-[11px] leading-[15px] text-ink-faint">
            Allow runs freely · Ask pauses for your approval · Block hides the tool
          </p>
          {tools === null ? (
            <p className="py-3 text-[12px] text-ink-faint">Loading tools…</p>
          ) : tools.length === 0 ? (
            <p className="py-3 text-[12px] text-ink-faint">
              No tools discovered yet. Connect the server to list its tools.
            </p>
          ) : (
            <>
              <div className="mt-1 divide-y divide-line rounded-lg border border-line px-3">
                {shownTools!.map((tool) => (
                  <ToolPermissionRow
                    key={tool.id}
                    tool={tool}
                    perm={permOf(tool)}
                    onChange={(p) => setPerm(tool, p)}
                  />
                ))}
              </div>
              {tools.length > 6 && (
                <button
                  onClick={() => setShowAll(!showAll)}
                  className="mt-1.5 cursor-pointer border-none bg-transparent text-[11px] font-medium text-accent"
                >
                  {showAll ? "Show fewer" : `+ ${tools.length - 6} more tools`}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-line px-4 py-3">
        <button
          onClick={onDelete}
          className="flex cursor-pointer items-center gap-1.5 border-none bg-transparent text-[12px] font-medium text-danger transition-opacity hover:opacity-80"
        >
          <Trash2 className="h-3.5 w-3.5" /> Remove server
        </button>
      </div>
    </div>
  );
}

function ToolPermissionRow({
  tool,
  perm,
  onChange,
}: {
  tool: McpToolInfo;
  perm: Perm;
  onChange: (p: Perm) => void;
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[12px] font-medium text-ink">{tool.tool_name}</p>
        <p className="truncate text-[11px] text-ink-muted" title={tool.description}>
          {tool.description}
        </p>
      </div>
      {tool.egress && (
        <span className="shrink-0 rounded-full bg-ground px-1.5 py-0.5 font-mono text-[9px] uppercase text-ink-faint">
          egress
        </span>
      )}
      <Select
        value={perm}
        onChange={(v) => onChange(v as Perm)}
        options={[
          { value: "allow", label: "Allow" },
          { value: "ask", label: "Ask" },
          { value: "block", label: "Block" },
        ]}
        className="shrink-0 cursor-pointer rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-medium text-ink-2 focus:border-accent focus:outline-none"
      />
    </div>
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
      style={{ borderColor: "var(--border)", background: "var(--ground)" }}
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
              borderColor: "var(--border)",
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
              border: "1px solid var(--border)",
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
    <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
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
              style={{ background: "var(--ground)" }}
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
  search,
  installedNames,
  onInstalled,
}: {
  search: string;
  installedNames: Set<string>;
  onInstalled: () => void;
}) {
  const [entries, setEntries] = useState<McpCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Debounce — the toolbar input types faster than the catalog query should fire.
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const fetchCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listMcpCatalog(
        category ?? undefined,
        debouncedSearch || undefined,
      );
      setEntries(list);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [category, debouncedSearch]);

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
            borderColor: "var(--border)",
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
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
          {entries.map((entry) => {
            const isInstalled = installedNames.has(entry.name);
            return (
              <div
                key={entry.name}
                className="flex flex-col rounded-xl border border-line bg-surface p-4 transition-colors hover:border-ink-faint"
              >
                {/* Header */}
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-accent-tint text-[15px] font-semibold text-accent">
                    {entry.name.charAt(0).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-medium text-ink">{entry.name}</p>
                    <p className="truncate font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                      {entry.vendor}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 font-mono text-[9px] uppercase ${
                      entry.auth_type === "none" ? "bg-accent-tint text-accent" : "bg-ground text-ink-muted"
                    }`}
                  >
                    {AUTH_LABELS[entry.auth_type] ?? entry.auth_type}
                  </span>
                </div>

                {/* Description */}
                <p className="mt-3 line-clamp-3 min-h-[48px] flex-1 text-[12px] leading-[16px] text-ink-2">
                  {entry.description}
                </p>

                {/* Footer */}
                <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                    {CATEGORY_LABELS[entry.category] ?? entry.category} · {entry.transport}
                  </span>
                  {isInstalled ? (
                    <span className="flex items-center gap-1 text-[12px] font-medium text-accent">
                      Installed
                    </span>
                  ) : entry.installable === false ? (
                    <a
                      href={entry.homepage}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-md border border-line px-3 py-1.5 text-[12px] font-medium text-ink-2 transition-colors hover:bg-sunken"
                    >
                      Setup required
                    </a>
                  ) : (
                    <button
                      onClick={() => handleInstall(entry.name)}
                      disabled={installing === entry.name}
                      className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-opacity ${
                        installing === entry.name
                          ? "cursor-not-allowed bg-ground text-ink-muted"
                          : "cursor-pointer bg-accent text-white hover:opacity-90"
                      }`}
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
        border: "1px solid var(--border)",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
