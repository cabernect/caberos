import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, MessageCircle, Search, Settings2, MoreHorizontal, TriangleAlert, Trash2, X } from "lucide-react";
import { DashboardSidebar, NAV_ROUTES, type NavKey } from "@/components/DashboardSidebar";
import { PageIntro } from "@/components/guidance/PageIntro";
import { INTRO_BY_KEY } from "@/components/guidance/tourStops";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusWord } from "@/components/ui/status-word";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { ChannelInfo, Agent } from "@/lib/types";

interface PlatformMeta {
  value: string;
  label: string;
  letter: string;
  tileBg: string;
  tileFg: string;
  subtitle: string;
  hint: string;
}

const PLATFORMS: PlatformMeta[] = [
  { value: "telegram", label: "Telegram", letter: "T", tileBg: "#e3efff", tileFg: "#2f6bd8", subtitle: "Bot token", hint: "Create a bot via @BotFather, paste the token here" },
  { value: "discord", label: "Discord", letter: "D", tileBg: "#ece7fb", tileFg: "#6a5acd", subtitle: "Bot token", hint: "Create a bot at discord.com/developers/applications, enable Message Content Intent, add bot to your server" },
  { value: "zalo_oa", label: "Zalo OA", letter: "Z", tileBg: "#e0f2ea", tileFg: "#2c8a5f", subtitle: "Webhook", hint: "Register OA at oa.zalo.me, create an App, OAuth login to get access_token" },
  { value: "zalo_bot", label: "Zalo Bot", letter: "Z", tileBg: "#e3efff", tileFg: "#2f6bd8", subtitle: "Bot token", hint: "Search 'Zalo Bot Manager' in Zalo app, create a bot, paste the bot token" },
];

function platformInfo(p: string): PlatformMeta {
  return PLATFORMS.find((x) => x.value === p) ?? {
    value: p, label: p, letter: p[0]?.toUpperCase() ?? "?", tileBg: "var(--sunken)", tileFg: "var(--ink-2)", subtitle: "", hint: "",
  };
}

const selectCls =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink focus:border-accent focus:outline-none cursor-pointer";

function FieldSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="min-w-0 flex-1">
      <label className="mb-1 block text-[12px] text-ink-muted">{label}</label>
      <Select
        value={value}
        onChange={onChange}
        options={options}
        className={selectCls}
        align="left" panelClassName="text-[13px]"
      />
    </div>
  );
}

export function Channels() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [channelFilter, setChannelFilter] = useState<"all" | "connected" | "paused">("all");
  const [search, setSearch] = useState("");
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

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editToken, setEditToken] = useState("");
  const [editSecret, setEditSecret] = useState("");
  const [editMode, setEditMode] = useState<"polling" | "webhook">("polling");
  const [editSaving, setEditSaving] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [editError, setEditError] = useState("");

  // Card chrome
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [addingChatFor, setAddingChatFor] = useState<string | null>(null);
  const [chatIdDraft, setChatIdDraft] = useState<Record<string, string>>({});

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
    navigate(NAV_ROUTES[page]);
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

  const startEdit = (ch: ChannelInfo) => {
    setEditingId(ch.id);
    setEditToken("");
    setEditSecret("");
    setEditMode(ch.mode as "polling" | "webhook");
    setEditError("");
  };

  const handleSaveEdit = async (id: string) => {
    setEditSaving(true);
    setEditError("");
    try {
      const updates: { bot_token?: string; webhook_secret?: string; mode?: string } = {};
      if (editToken.trim()) updates.bot_token = editToken.trim();
      if (editSecret.trim()) updates.webhook_secret = editSecret.trim();
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

  const handleAgentChange = async (ch: ChannelInfo, agentIdNew: string) => {
    try {
      await api.updateChannel(ch.id, { agent_id: agentIdNew });
      await fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change agent");
    }
  };

  const handlePolicyChange = async (ch: ChannelInfo, policy: string) => {
    try {
      await api.updateChannel(ch.id, {
        // "restricted" keeps the current list (empty = nobody, matches the warning UI)
        allowed_chat_ids: policy === "restricted" ? (ch.allowed_chat_ids ?? []) : null,
      });
      await fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update allow list");
    }
  };

  const handleAddChatId = async (ch: ChannelInfo) => {
    const id = (chatIdDraft[ch.id] || "").trim();
    if (!id) return;
    try {
      await api.updateChannel(ch.id, {
        allowed_chat_ids: [...(ch.allowed_chat_ids ?? []), id],
      });
      setChatIdDraft((prev) => ({ ...prev, [ch.id]: "" }));
      setAddingChatFor(null);
      await fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add chat ID");
    }
  };

  const handleRemoveChatId = async (ch: ChannelInfo, chatId: string) => {
    try {
      await api.updateChannel(ch.id, {
        allowed_chat_ids: (ch.allowed_chat_ids ?? []).filter((c) => c !== chatId),
      });
      await fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove chat ID");
    }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--ground)" }}>
      <DashboardSidebar
        active="channels"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[{ label: "Capabilities" }, { label: "Channels" }]}
          title="Channels"
          subtitle="Chat with your agents from the apps you already use."
          actions={
            <Button onClick={() => setShowAdd(true)}>
              <Plus />Add channel
            </Button>
          }
        />

        <div className="px-8 pt-4">
          <PageIntro def={INTRO_BY_KEY.channels} />
        </div>

        {/* Filter row — pinned below the header */}
        <div className="px-8 pb-4">
          <div className="flex flex-wrap items-center gap-3">
            <FilterPills
              pills={[
                { key: "all", label: "All", count: channels.length },
                { key: "connected", label: "Connected", count: channels.filter((c) => c.enabled).length },
                { key: "paused", label: "Paused", count: channels.filter((c) => !c.enabled).length },
              ]}
              active={channelFilter}
              onChange={(k) => setChannelFilter(k as typeof channelFilter)}
              variant="segmented"
            />
            {channels.length > 0 && (
              <div className="relative ml-auto w-[240px]">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search channels"
                  className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                />
              </div>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 pb-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="min-w-0 lg:col-span-2">

            {/* Channel list */}
            {(() => {
              const q = search.trim().toLowerCase();
              const visible = channels.filter((ch) => {
                if (channelFilter === "connected" && !ch.enabled) return false;
                if (channelFilter === "paused" && ch.enabled) return false;
                if (q) {
                  const info = platformInfo(ch.platform);
                  const hay = `${info?.label ?? ""} ${ch.platform} ${agentName(ch.agent_id)}`.toLowerCase();
                  if (!hay.includes(q)) return false;
                }
                return true;
              });
              if (loading)
                return <p className="py-20 text-center text-[14px] text-ink-faint">Loading…</p>;
              if (channels.length === 0)
                return (
                  <EmptyState icon={MessageCircle} title="No channels configured yet">
                    Add a Telegram, Discord, or Zalo bot to chat with your agent from anywhere.
                  </EmptyState>
                );
              if (visible.length === 0)
                return (
                  <p className="py-12 text-center text-[13px] text-ink-faint">
                    No channels match this filter.
                  </p>
                );
              return (
              <div className="space-y-3">
                {visible.map((ch) => {
                  const info = platformInfo(ch.platform);
                  const restricted = ch.allowed_chat_ids !== null;
                  const emptyList = restricted && ch.allowed_chat_ids!.length === 0;
                  return (
                    <div
                      key={ch.id}
                      className="rounded-xl border border-line bg-surface p-4"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <span
                            className="flex h-9 w-9 items-center justify-center rounded-lg text-[15px] font-semibold"
                            style={{ background: info.tileBg, color: info.tileFg }}
                          >
                            {info.letter}
                          </span>
                          <div>
                            <p className="text-[14px] font-semibold text-ink">
                              {info.label}
                            </p>
                            <StatusWord
                              status={ch.enabled ? "success" : "paused"}
                              label={
                                ch.enabled
                                  ? `Live · ${ch.mode} · replies with ${agentName(ch.agent_id)}`
                                  : `Paused · ${ch.mode} · messages are not being read`
                              }
                            />
                          </div>
                        </div>
                        <div className="relative flex items-center gap-2">
                          <Toggle
                            checked={ch.enabled}
                            onCheckedChange={() => handleToggleEnabled(ch)}
                            aria-label={`${ch.enabled ? "Disable" : "Enable"} ${info.label} channel`}
                            title={ch.enabled ? "Disable channel" : "Enable channel"}
                            disabled={togglingId === ch.id}
                          />
                          <button
                            onClick={() => setMenuFor(menuFor === ch.id ? null : ch.id)}
                            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-ink-faint transition hover:bg-sunken hover:text-ink"
                            title="Channel actions"
                          >
                            <MoreHorizontal className="h-4 w-4" />
                          </button>
                          {menuFor === ch.id && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setMenuFor(null)} />
                              <div className="absolute right-0 top-8 z-20 min-w-[160px] overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-lg">
                                <button
                                  onClick={() => {
                                    setMenuFor(null);
                                    startEdit(ch);
                                  }}
                                  className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-[12.5px] text-ink-2 transition-colors hover:bg-sunken hover:text-ink"
                                >
                                  <Settings2 className="h-3.5 w-3.5" /> Edit settings
                                </button>
                                <button
                                  onClick={() => {
                                    setMenuFor(null);
                                    handleDelete(ch.id, ch.platform);
                                  }}
                                  className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-[12.5px] text-danger transition-colors hover:bg-danger-tint"
                                >
                                  <Trash2 className="h-3.5 w-3.5" /> Remove channel
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Routing + allow-list controls */}
                      <div className="mt-4 flex flex-wrap gap-3">
                        <FieldSelect
                          label="Replies with"
                          value={ch.agent_id}
                          options={agents.map((a) => ({ value: a.id, label: a.name }))}
                          onChange={(v) => handleAgentChange(ch, v)}
                        />
                        <FieldSelect
                          label="Allowed senders"
                          value={restricted ? "restricted" : "anyone"}
                          options={[
                            { value: "anyone", label: "Anyone who finds the bot" },
                            { value: "restricted", label: "Allowed chat IDs only" },
                          ]}
                          onChange={(v) => handlePolicyChange(ch, v)}
                        />
                      </div>

                      {/* Allow-list state */}
                      {restricted && (
                        <div className="mt-3">
                          {emptyList ? (
                            <div className="flex items-center justify-between gap-3 rounded-lg bg-accent-tint px-3 py-2.5">
                              <p className="flex items-center gap-2 text-[12.5px] text-ink">
                                <TriangleAlert className="h-4 w-4 shrink-0 text-accent" />
                                No chat IDs added yet — turn this on and nobody can reach the agent.
                              </p>
                              <button
                                onClick={() => setAddingChatFor(ch.id)}
                                className="shrink-0 cursor-pointer border-none bg-transparent text-[12.5px] font-medium text-accent hover:underline"
                              >
                                Add chat ID
                              </button>
                            </div>
                          ) : (
                            <div className="flex flex-wrap items-center gap-1.5">
                              {ch.allowed_chat_ids!.map((cid) => (
                                <span
                                  key={cid}
                                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-sunken px-2.5 py-1 font-mono text-[12px] text-ink"
                                >
                                  {cid}
                                  <button
                                    onClick={() => handleRemoveChatId(ch, cid)}
                                    className="flex h-3.5 w-3.5 cursor-pointer items-center justify-center border-none bg-transparent p-0 text-ink-faint transition hover:text-danger"
                                    title={`Remove ${cid}`}
                                  >
                                    <X className="h-3 w-3" />
                                  </button>
                                </span>
                              ))}
                              <button
                                onClick={() => setAddingChatFor(addingChatFor === ch.id ? null : ch.id)}
                                className="cursor-pointer border-none bg-transparent px-1 text-[12.5px] font-medium text-accent hover:underline"
                              >
                                + Add
                              </button>
                            </div>
                          )}
                          {addingChatFor === ch.id && (
                            <div className="mt-2 flex gap-2">
                              <input
                                type="text"
                                value={chatIdDraft[ch.id] || ""}
                                onChange={(e) =>
                                  setChatIdDraft((prev) => ({ ...prev, [ch.id]: e.target.value }))
                                }
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") handleAddChatId(ch);
                                  if (e.key === "Escape") setAddingChatFor(null);
                                }}
                                placeholder="Chat ID, e.g. 123456789"
                                autoFocus
                                className="flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-[12px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                              />
                              <Button variant="secondary" onClick={() => handleAddChatId(ch)}>Add</Button>
                              <Button variant="secondary" onClick={() => setAddingChatFor(null)}>Cancel</Button>
                            </div>
                          )}
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

                    </div>
                  );
                })}
              </div>
              );
            })()}
          </div>

          {/* Available to connect — platforms without a channel yet */}
          {(() => {
            const used = new Set(channels.map((c) => c.platform));
            const available = PLATFORMS.filter((p) => !used.has(p.value));
            if (available.length === 0) return null;
            return (
              <aside>
                <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                  Available to connect
                </p>
                <div className="space-y-3">
                  {available.map((p) => (
                    <div
                      key={p.value}
                      className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3"
                    >
                      <span
                        className="flex h-9 w-9 items-center justify-center rounded-lg text-[15px] font-semibold"
                        style={{ background: p.tileBg, color: p.tileFg }}
                      >
                        {p.letter}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[14px] font-semibold text-ink">{p.label}</p>
                        <p className="text-[12px] text-ink-muted">{p.subtitle}</p>
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setPlatform(p.value);
                          setShowAdd(true);
                        }}
                      >
                        <Plus />Connect
                      </Button>
                    </div>
                  ))}
                </div>
              </aside>
            );
          })()}
          </div>
        </div>
      </div>

      {editingId && channels.find((c) => c.id === editingId) && (
        <EditChannelModal
          channel={channels.find((c) => c.id === editingId)!}
          token={editToken}
          setToken={setEditToken}
          secret={editSecret}
          setSecret={setEditSecret}
          mode={editMode}
          setMode={setEditMode}
          saving={editSaving}
          error={editError}
          onClose={() => setEditingId(null)}
          onSubmit={() => handleSaveEdit(editingId)}
        />
      )}

      {showAdd && (
        <AddChannelModal
          platform={platform}
          setPlatform={setPlatform}
          agentId={agentId}
          setAgentId={setAgentId}
          agents={agents}
          botToken={botToken}
          setBotToken={setBotToken}
          webhookSecret={webhookSecret}
          setWebhookSecret={setWebhookSecret}
          mode={mode}
          setMode={setMode}
          saving={saving}
          error={error}
          onClose={() => {
            setShowAdd(false);
            setError("");
          }}
          onSubmit={handleAdd}
        />
      )}
    </div>
  );
}

function EditChannelModal({
  channel,
  token,
  setToken,
  secret,
  setSecret,
  mode,
  setMode,
  saving,
  error,
  onClose,
  onSubmit,
}: {
  channel: ChannelInfo;
  token: string;
  setToken: (v: string) => void;
  secret: string;
  setSecret: (v: string) => void;
  mode: "polling" | "webhook";
  setMode: (v: "polling" | "webhook") => void;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const info = platformInfo(channel.platform);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-[440px] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span
              className="flex h-7 w-7 items-center justify-center rounded-md text-[12px] font-semibold"
              style={{ background: info.tileBg, color: info.tileFg }}
            >
              {info.letter}
            </span>
            <h3 className="text-[14px] font-semibold text-ink">{info.label} settings</h3>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-ink-faint transition hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-3.5">
            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Bot Token</label>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={channel.has_token ? "•••••••• (leave blank to keep current)" : "Paste the bot token"}
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[12px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Webhook Secret</label>
              <input
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={
                  channel.has_webhook_secret
                    ? "•••••••• (leave blank to keep current)"
                    : "Secret token for webhook validation"
                }
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Mode</label>
              <div className="flex gap-4">
                {(["polling", "webhook"] as const).map((m) => (
                  <label key={m} className="flex cursor-pointer items-center gap-1.5 text-[13px] text-ink">
                    <input
                      type="radio"
                      checked={mode === m}
                      onChange={() => setMode(m)}
                    />
                    {m === "polling" ? "Polling" : "Webhook"}
                  </label>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-ink-faint">
                {mode === "polling"
                  ? channel.platform === "discord"
                    ? "Note: Discord polling requires gateway WebSocket (not yet supported). Use webhook mode for Discord."
                    : channel.platform === "zalo_oa"
                    ? "Note: Zalo OA requires webhook mode (no polling API). Use webhook mode."
                    : "Bot polls the platform for updates. Works from localhost — no public URL needed."
                  : "Platform pushes updates to your public URL. Lower latency, but needs ngrok/cloudflare tunnel or a public server."}
              </p>
              {mode === "webhook" && channel.webhook_url && (
                <div className="mt-2">
                  <div className="break-all rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[11px] text-ink-2">
                    {window.location.origin}{channel.webhook_url}
                  </div>
                  <p className="mt-1 text-[11px] text-ink-faint">
                    Set this as your bot's webhook URL
                    {channel.platform === "telegram" ? " via @BotFather → /setwebhook" : ""}
                    {channel.platform === "discord" ? " in Discord Developer Portal → Webhooks" : ""}
                    {channel.platform === "zalo_oa" ? " in OA Manager → Webhook settings (HTTPS required)" : ""}
                    {channel.platform === "zalo_bot" ? " — CaberOS auto-registers on startup" : ""}
                  </p>
                </div>
              )}
            </div>

            {error && <p className="text-[12px] text-danger">{error}</p>}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={onSubmit} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function AddChannelModal({
  platform,
  setPlatform,
  agentId,
  setAgentId,
  agents,
  botToken,
  setBotToken,
  webhookSecret,
  setWebhookSecret,
  mode,
  setMode,
  saving,
  error,
  onClose,
  onSubmit,
}: {
  platform: string;
  setPlatform: (v: string) => void;
  agentId: string;
  setAgentId: (v: string) => void;
  agents: Agent[];
  botToken: string;
  setBotToken: (v: string) => void;
  webhookSecret: string;
  setWebhookSecret: (v: string) => void;
  mode: "polling" | "webhook";
  setMode: (v: "polling" | "webhook") => void;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const info = platformInfo(platform);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-[440px] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h3 className="text-[14px] font-semibold text-ink">Add channel</h3>
          <button
            onClick={onClose}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-ink-faint transition hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-3.5">
            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Platform</label>
              <div className="grid grid-cols-2 gap-2">
                {PLATFORMS.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    onClick={() => setPlatform(p.value)}
                    className={`flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition ${
                      platform === p.value
                        ? "border-accent bg-accent-tint"
                        : "border-line bg-surface hover:border-ink-faint"
                    }`}
                  >
                    <span
                      className="flex h-7 w-7 items-center justify-center rounded-md text-[12px] font-semibold"
                      style={{ background: p.tileBg, color: p.tileFg }}
                    >
                      {p.letter}
                    </span>
                    <span className="text-[13px] font-medium text-ink">{p.label}</span>
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-ink-faint">{info.hint}</p>
            </div>

            <FieldSelect
              label="Replies with"
              value={agentId}
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              onChange={setAgentId}
            />

            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Bot Token</label>
              <input
                type="password"
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[12px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">
                Webhook Secret (optional)
              </label>
              <input
                type="text"
                value={webhookSecret}
                onChange={(e) => setWebhookSecret(e.target.value)}
                placeholder="Secret token for webhook validation"
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] text-ink-muted">Mode</label>
              <div className="flex gap-4">
                {(["polling", "webhook"] as const).map((m) => (
                  <label key={m} className="flex cursor-pointer items-center gap-1.5 text-[13px] text-ink">
                    <input
                      type="radio"
                      checked={mode === m}
                      onChange={() => setMode(m)}
                    />
                    {m === "polling" ? "Polling" : "Webhook"}
                  </label>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-ink-faint">
                {mode === "polling"
                  ? platform === "discord"
                    ? "Note: Discord polling requires gateway WebSocket (not yet supported). Use webhook mode for Discord."
                    : platform === "zalo_oa"
                    ? "Note: Zalo OA requires webhook mode (no polling API). Use webhook mode."
                    : "Bot polls the platform for updates. Works from localhost — no public URL needed."
                  : "Platform pushes updates to your public URL. Lower latency, but needs ngrok/cloudflare tunnel or a public server."}
              </p>
            </div>

            {error && <p className="text-[12px] text-danger">{error}</p>}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={onSubmit} disabled={saving}>
            {saving ? "Saving…" : "Add channel"}
          </Button>
        </div>
      </div>
    </div>
  );
}
