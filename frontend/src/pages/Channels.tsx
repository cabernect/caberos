import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Radio, Plus, Trash2, Send, MessageCircle, Settings2 } from "lucide-react";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { ChannelInfo, Agent } from "@/lib/types";

const PLATFORMS = [
  { value: "telegram", label: "Telegram", icon: "✈️", hint: "Create a bot via @BotFather, paste the token here" },
  { value: "discord", label: "Discord", icon: "🎮", hint: "Create a bot at discord.com/developers/applications, enable Message Content Intent, add bot to your server" },
  { value: "zalo_oa", label: "Zalo OA", icon: "💬", hint: "Register OA at oa.zalo.me, create an App, OAuth login to get access_token" },
  { value: "zalo_bot", label: "Zalo Bot", icon: "🤖", hint: "Search 'Zalo Bot Manager' in Zalo app, create a bot, paste the bot token" },
];

export function Channels() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const navigate = useNavigate();
  const { confirm } = useConfirm();

  // Add form state
  const [platform, setPlatform] = useState("telegram");
  const [agentId, setAgentId] = useState("");
  const [botToken, setBotToken] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [mode, setMode] = useState<"polling" | "webhook">("polling");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Test state (per-channel)
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testChatIds, setTestChatIds] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, string>>({});

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editToken, setEditToken] = useState("");
  const [editMode, setEditMode] = useState<"polling" | "webhook">("polling");
  const [editSaving, setEditSaving] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [editError, setEditError] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [chans, ags] = await Promise.all([api.listChannels(), api.listAgents()]);
      setChannels(chans);
      setAgents(ags);
      if (ags.length > 0 && !agentId) setAgentId(ags[0].id);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

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
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") return;
    if (page === "observability") navigate("/observability");
    if (page === "traces") navigate("/traces");
  };

  const handleAdd = async () => {
    setError("");
    if (!agentId) {
      setError("Select an agent");
      return;
    }
    if (!botToken.trim()) {
      setError("Bot token is required");
      return;
    }
    setSaving(true);
    try {
      await api.createChannel({
        platform,
        agent_id: agentId,
        bot_token: botToken.trim(),
        webhook_secret: webhookSecret.trim() || undefined,
        mode,
      });
      setShowAdd(false);
      setBotToken("");
      setWebhookSecret("");
      setMode("polling");
      fetchData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add channel");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string, platform: string) => {
    const ok = await confirm({
      title: "Remove channel?",
      message: `Remove this ${platform} channel?`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteChannel(id);
      fetchData();
    } catch {
      // ignore
    }
  };

  const handleTest = async (id: string) => {
    const chatId = testChatIds[id] || "";
    if (!chatId.trim()) {
      setTestResults((prev) => ({ ...prev, [id]: "Enter a chat ID to send the test to" }));
      return;
    }
    setTestingId(id);
    setTestResults((prev) => ({ ...prev, [id]: "" }));
    try {
      const result = await api.testChannel(id, chatId.trim());
      setTestResults((prev) => ({
        ...prev,
        [id]: result.success ? "✅ Test message sent!" : `❌ ${result.error}`,
      }));
    } catch (e: unknown) {
      setTestResults((prev) => ({
        ...prev,
        [id]: `❌ ${e instanceof Error ? e.message : "Test failed"}`,
      }));
    } finally {
      setTestingId(null);
    }
  };

  const startEdit = (ch: ChannelInfo) => {
    setEditingId(ch.id);
    setEditToken("");
    setEditMode(ch.mode as "polling" | "webhook");
    setEditError("");
  };

  const handleSaveEdit = async (id: string) => {
    setEditSaving(true);
    setEditError("");
    try {
      const updates: { bot_token?: string; mode?: string; enabled?: boolean } = {};
      if (editToken.trim()) updates.bot_token = editToken.trim();
      if (editMode) updates.mode = editMode;
      await api.updateChannel(id, updates);
      setEditingId(null);
      fetchData();
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setEditSaving(false);
    }
  };

  const handleToggleEnabled = async (channel: ChannelInfo) => {
    setTogglingId(channel.id);
    try {
      await api.updateChannel(channel.id, { enabled: !channel.enabled });
      await fetchData();
    } catch {
      // ignore
    } finally {
      setTogglingId(null);
    }
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id;
  const platformInfo = (p: string) => PLATFORMS.find((x) => x.value === p);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="channels"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          icon={Radio}
          title="Channels"
          description="Connect external messaging platforms — chat with your agent from Telegram, Discord, and more"
        />

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-3xl">
            {/* Add button */}
            <div className="mb-4 flex justify-end">
              <button
                onClick={() => setShowAdd(!showAdd)}
                className="flex items-center gap-1.5 rounded-[6px] px-3 py-1.5 text-[13px] font-medium"
                style={{ background: "var(--accent)", color: "white" }}
              >
                <Plus className="h-4 w-4" />
                Add Channel
              </button>
            </div>

            {/* Add form */}
            {showAdd && (
              <div
                className="mb-4 rounded-[8px] border p-4"
                style={{ borderColor: "var(--border)", background: "var(--white)" }}
              >
                <h3 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">New Channel</h3>
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-[12px] text-[var(--ink-2)]">Platform</label>
                    <select
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                      className="w-full rounded-[4px] border px-2 py-1.5 text-[13px]"
                      style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                    >
                      {PLATFORMS.map((p) => (
                        <option key={p.value} value={p.value}>
                          {p.icon} {p.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                      {platformInfo(platform)?.hint}
                    </p>
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] text-[var(--ink-2)]">Agent</label>
                    <select
                      value={agentId}
                      onChange={(e) => setAgentId(e.target.value)}
                      className="w-full rounded-[4px] border px-2 py-1.5 text-[13px]"
                      style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                    >
                      {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] text-[var(--ink-2)]">Bot Token</label>
                    <input
                      type="password"
                      value={botToken}
                      onChange={(e) => setBotToken(e.target.value)}
                      placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                      className="w-full rounded-[4px] border px-2 py-1.5 font-mono text-[12px]"
                      style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] text-[var(--ink-2)]">
                      Webhook Secret (optional)
                    </label>
                    <input
                      type="text"
                      value={webhookSecret}
                      onChange={(e) => setWebhookSecret(e.target.value)}
                      placeholder="Secret token for webhook validation"
                      className="w-full rounded-[4px] border px-2 py-1.5 text-[13px]"
                      style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] text-[var(--ink-2)]">Mode</label>
                    <div className="flex gap-4">
                      <label className="flex items-center gap-1.5 text-[13px]" style={{ color: "var(--ink)" }}>
                        <input
                          type="radio"
                          checked={mode === "polling"}
                          onChange={() => setMode("polling")}
                        />
                        Polling
                      </label>
                      <label className="flex items-center gap-1.5 text-[13px]" style={{ color: "var(--ink)" }}>
                        <input
                          type="radio"
                          checked={mode === "webhook"}
                          onChange={() => setMode("webhook")}
                        />
                        Webhook
                      </label>
                    </div>
                    <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                      {mode === "polling"
                        ? platform === "discord"
                          ? "Note: Discord polling requires gateway WebSocket (not yet supported). Use webhook mode for Discord."
                          : platform === "zalo_oa"
                          ? "Note: Zalo OA requires webhook mode (no polling API). Use webhook mode."
                          : "Bot polls the platform for updates. Works from localhost — no public URL needed."
                        : "Platform pushes updates to your public URL. Lower latency, but needs ngrok/cloudflare tunnel or a public server."}
                    </p>
                  </div>
                  {error && (
                    <p className="text-[12px] text-red-500">{error}</p>
                  )}
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => setShowAdd(false)}
                      className="rounded-[4px] px-3 py-1.5 text-[13px]"
                      style={{ color: "var(--ink-2)" }}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleAdd}
                      disabled={saving}
                      className="rounded-[4px] px-3 py-1.5 text-[13px] font-medium"
                      style={{ background: "var(--accent)", color: "white" }}
                    >
                      {saving ? "Saving..." : "Save"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Channel list */}
            {loading ? (
              <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Loading...</p>
            ) : channels.length === 0 ? (
              <div className="py-12 text-center">
                <MessageCircle className="mx-auto mb-3 h-10 w-10 opacity-30" style={{ color: "var(--ink-3)" }} />
                <p className="text-[14px] text-[var(--ink-2)]">No channels configured yet</p>
                <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                  Add a Telegram, Discord, or Zalo bot to chat with your agent from anywhere
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {channels.map((ch) => {
                  const info = platformInfo(ch.platform);
                  return (
                    <div
                      key={ch.id}
                      className="rounded-[8px] border p-4"
                      style={{ borderColor: "var(--border)", background: "var(--white)" }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <span className="text-2xl">{info?.icon || "📡"}</span>
                          <div>
                            <p className="text-[14px] font-semibold text-[var(--ink)]">
                              {info?.label || ch.platform}
                            </p>
                            <p className="text-[12px] text-[var(--ink-2)]">
                              Agent: {agentName(ch.agent_id)} · {ch.mode === "polling" ? "Polling" : "Webhook"}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ch.enabled}
                            aria-label={`${ch.enabled ? "Disable" : "Enable"} ${info?.label || ch.platform} channel`}
                            title={ch.enabled ? "Disable channel" : "Enable channel"}
                            disabled={togglingId === ch.id}
                            onClick={() => handleToggleEnabled(ch)}
                            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-60 ${ch.enabled ? "border-[var(--accent)] bg-[var(--accent)]" : "border-[var(--border)] bg-[var(--sidebar)]"}`}
                          >
                            <span
                              className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${ch.enabled ? "translate-x-6" : "translate-x-1"}`}
                            />
                          </button>
                          <button
                            onClick={() => startEdit(ch)}
                            className="rounded-[4px] p-1.5 text-[var(--ink-3)] hover:text-[var(--ink)]"
                            title="Edit channel"
                          >
                            <Settings2 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(ch.id, ch.platform)}
                            className="rounded-[4px] p-1.5 text-[var(--ink-3)] hover:text-red-500"
                            title="Remove channel"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>

                      {/* Edit form (inline) */}
                      {editingId === ch.id && (
                        <div
                        className="mt-3 rounded-[6px] border p-3"
                        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                      >
                        <div className="space-y-2">
                          <div>
                            <label className="mb-1 block text-[11px] text-[var(--ink-3)]">
                              Bot Token (leave blank to keep current)
                            </label>
                            <input
                              type="password"
                              value={editToken}
                              onChange={(e) => setEditToken(e.target.value)}
                              placeholder="•••••••• (unchanged)"
                              className="w-full rounded-[4px] border px-2 py-1.5 font-mono text-[12px]"
                              style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-[var(--ink-3)]">Mode</label>
                            <div className="flex gap-4">
                              <label className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--ink)" }}>
                                <input
                                  type="radio"
                                  checked={editMode === "polling"}
                                  onChange={() => setEditMode("polling")}
                                />
                                Polling
                              </label>
                              <label className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--ink)" }}>
                                <input
                                  type="radio"
                                  checked={editMode === "webhook"}
                                  onChange={() => setEditMode("webhook")}
                                />
                                Webhook
                              </label>
                            </div>
                          </div>
                          {editError && (
                            <p className="text-[12px] text-red-500">{editError}</p>
                          )}
                          <div className="flex justify-end gap-2">
                            <button
                              onClick={() => setEditingId(null)}
                              className="rounded-[4px] px-3 py-1 text-[12px]"
                              style={{ color: "var(--ink-2)" }}
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => handleSaveEdit(ch.id)}
                              disabled={editSaving}
                              className="rounded-[4px] px-3 py-1 text-[12px] font-medium"
                              style={{ background: "var(--accent)", color: "white" }}
                            >
                              {editSaving ? "Saving..." : "Save"}
                            </button>
                          </div>
                        </div>
                      </div>
                      )}

                      {/* Webhook URL (only shown for webhook mode) */}
                      {ch.mode === "webhook" && (
                        <div className="mt-3">
                          <label className="mb-1 block text-[11px] text-[var(--ink-3)]">Webhook URL</label>
                          <div
                            className="rounded-[4px] border px-2 py-1.5 font-mono text-[11px] break-all"
                            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink-2)" }}
                          >
                            {window.location.origin}{ch.webhook_url}
                          </div>
                          <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                            Set this as your bot's webhook URL
                            {ch.platform === "telegram" ? " via @BotFather → /setwebhook" : ""}
                            {ch.platform === "discord" ? " in Discord Developer Portal → Webhooks" : ""}
                            {ch.platform === "zalo_oa" ? " in OA Manager → Webhook settings (HTTPS required)" : ""}
                            {ch.platform === "zalo_bot" ? " — CaberOS auto-registers on startup" : ""}
                          </p>
                        </div>
                      )}
                      {ch.mode === "polling" && (
                        <div className="mt-3">
                          <p className="text-[11px] text-[var(--ink-3)]">
                            ✅ Polling active — CaberOS is checking for new messages. No webhook setup needed.
                          </p>
                        </div>
                      )}

                      {/* Test section */}
                      <div className="mt-3 flex items-end gap-2">
                        <div className="flex-1">
                          <label className="mb-1 block text-[11px] text-[var(--ink-3)]">
                            Test — send a message to a chat ID
                          </label>
                          <input
                            type="text"
                            value={testChatIds[ch.id] || ""}
                            onChange={(e) =>
                              setTestChatIds((prev) => ({ ...prev, [ch.id]: e.target.value }))
                            }
                            placeholder="e.g. 123456789"
                            className="w-full rounded-[4px] border px-2 py-1 text-[12px]"
                            style={{ borderColor: "var(--border)", background: "var(--white)", color: "var(--ink)" }}
                          />
                        </div>
                        <button
                          onClick={() => handleTest(ch.id)}
                          disabled={testingId === ch.id}
                          className="flex items-center gap-1 rounded-[4px] border px-2.5 py-1.5 text-[12px]"
                          style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
                        >
                          <Send className="h-3.5 w-3.5" />
                          {testingId === ch.id ? "Sending..." : "Test"}
                        </button>
                      </div>
                      {testResults[ch.id] && (
                        <p className="mt-2 text-[12px]">{testResults[ch.id]}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
