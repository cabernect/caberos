import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Key, Save, X, RefreshCw, Check, Info, Settings, Server, Cpu } from "lucide-react";
import { api } from "@/lib/api";
import type { Provider, ModelInfo, Operator } from "@/lib/types";
import { DashboardSidebar, type NavKey } from "@/components/DashboardSidebar";
import { LogoMark } from "@/components/LogoMark";

// Preset providers — known services with sensible defaults
const PRESET_PROVIDERS = [
  { type: "openai", name: "OpenAI", description: "GPT-4o, o1, o3, and more", defaultBaseUrl: "", needsKey: true },
  { type: "anthropic", name: "Anthropic", description: "Claude 3.5 Sonnet, Opus, Haiku", defaultBaseUrl: "", needsKey: true },
  { type: "gemini", name: "Google Gemini", description: "Gemini 2.0 Flash, Pro, and more", defaultBaseUrl: "", needsKey: true },
  { type: "deepseek", name: "DeepSeek", description: "DeepSeek V3, R1, Coder", defaultBaseUrl: "", needsKey: true },
  { type: "openrouter", name: "OpenRouter", description: "Multi-provider routing — 300+ models", defaultBaseUrl: "", needsKey: true },
  { type: "fireworks_ai", name: "Fireworks AI", description: "OpenAI-compatible model API", defaultBaseUrl: "", needsKey: true },
  { type: "xai", name: "xAI (Grok)", description: "Grok models via direct API", defaultBaseUrl: "", needsKey: true },
  { type: "mistral", name: "Mistral AI", description: "Mistral Large, Codestral, and more", defaultBaseUrl: "", needsKey: true },
  { type: "ollama", name: "Ollama (Local)", description: "Run models locally — Llama, Qwen, etc.", defaultBaseUrl: "http://localhost:11434", needsKey: false },
  { type: "azure", name: "Azure OpenAI", description: "Enterprise OpenAI via Azure", defaultBaseUrl: "", needsKey: true },
  { type: "bedrock", name: "AWS Bedrock", description: "Claude, Nova, Llama via Converse API", defaultBaseUrl: "", needsKey: true },
  { type: "huggingface", name: "Hugging Face", description: "20+ open models via unified router", defaultBaseUrl: "", needsKey: true },
  { type: "nvidia_nim", name: "NVIDIA NIM", description: "Nemotron models via build.nvidia.com", defaultBaseUrl: "", needsKey: true },
  { type: "cohere", name: "Cohere", description: "Command R+, Aya, and more", defaultBaseUrl: "", needsKey: true },
  { type: "ai21", name: "AI21 Labs", description: "Jamba models", defaultBaseUrl: "", needsKey: true },
  { type: "together_ai", name: "Together AI", description: "Open models on fast inference", defaultBaseUrl: "", needsKey: true },
  { type: "groq", name: "Groq", description: "Ultra-fast inference for open models", defaultBaseUrl: "", needsKey: true },
  { type: "perplexity", name: "Perplexity", description: "Perplexity Online/Sonar models", defaultBaseUrl: "", needsKey: true },
  { type: "dashscope", name: "Alibaba (Qwen)", description: "Qwen models via DashScope", defaultBaseUrl: "", needsKey: true },
  { type: "moonshot", name: "Moonshot (Kimi)", description: "Kimi coding and chat models", defaultBaseUrl: "", needsKey: true },
  { type: "zhipu", name: "Z.AI (GLM)", description: "GLM / Zhipu-hosted models", defaultBaseUrl: "", needsKey: true },
  { type: "minimax", name: "MiniMax", description: "MiniMax frontier model", defaultBaseUrl: "", needsKey: true },
  // OpenAI-compatible endpoints (use type "openai" with custom base_url)
  { type: "openai", name: "NovitaAI", description: "Multi-model API gateway", defaultBaseUrl: "https://api.novita.ai/v1", needsKey: true, compatOnly: true },
  { type: "openai", name: "LM Studio (Local)", description: "Local desktop app, OpenAI-compatible", defaultBaseUrl: "http://localhost:1234/v1", needsKey: false, compatOnly: true },
  { type: "openai", name: "Vercel AI Gateway", description: "Vercel AI Gateway routing", defaultBaseUrl: "https://ai-gateway.vercel.sh/v1", needsKey: true, compatOnly: true },
  { type: "openai", name: "vLLM / SGLang", description: "Self-hosted OpenAI-compatible server", defaultBaseUrl: "http://localhost:8000/v1", needsKey: false, compatOnly: true },
  { type: "openai", name: "OpenCode Zen", description: "Pay-per-use — GPT-5.x, Claude, Gemini, open models", defaultBaseUrl: "https://opencode.ai/zen/v1", needsKey: true, compatOnly: true },
  { type: "openai", name: "OpenCode Go", description: "$10/mo subscription — GLM, Kimi, DeepSeek, MiMo", defaultBaseUrl: "https://opencode.ai/zen/go/v1", needsKey: true, compatOnly: true },
  { type: "openai", name: "Ollama Cloud", description: "Hosted Ollama — gpt-oss, kimi-k2, llama4, and more", defaultBaseUrl: "https://ollama.com/v1", needsKey: true, compatOnly: true },
] as const;

type SettingsTab = "general" | "providers" | "models" | "about";

export function ProvidersSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [operator, setOperator] = useState<Operator | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [addingPreset, setAddingPreset] = useState<number | null>(null);  // preset index being configured
  const [showCustom, setShowCustom] = useState(false);  // custom provider form
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const [provs, me] = await Promise.all([api.listProviders(), api.me()]);
      setProviders(provs);
      setOperator(me);
    } catch {
      navigate("/login");
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => { load(); }, [load]);

  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    if (page === "agents") navigate("/agents");
    if (page === "settings") return;
    if (page === "vault") navigate("/vault");
    if (page === "skills") navigate("/skills");
    if (page === "scheduler") navigate("/scheduler");
    if (page === "mcps") navigate("/mcps");
    if (page === "channels") navigate("/channels");
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this provider? Agents using it will need to be reconfigured.")) return;
    try {
      await api.deleteProvider(id);
      load();
    } catch (e) {
      alert(String(e));
    }
  };

  const tabs: { key: SettingsTab; label: string; icon: typeof Settings }[] = [
    { key: "general", label: "General", icon: Settings },
    { key: "providers", label: "Providers", icon: Server },
    { key: "models", label: "Models", icon: Cpu },
    { key: "about", label: "About", icon: Info },
  ];

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      <DashboardSidebar
        active="settings"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        agentCount={0}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="px-8 py-5"
          style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
        >
          <h1 className="text-[18px] font-semibold text-[var(--ink)]">Settings</h1>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">Manage your CaberOS configuration</p>
        </div>

        {/* Tabs */}
        <div
          className="flex items-center gap-1 px-8 pt-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className="flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition"
                style={{
                  border: "none",
                  background: "none",
                  cursor: "pointer",
                  color: isActive ? "var(--ink)" : "var(--ink-3)",
                  borderBottom: isActive ? "2px solid var(--ink)" : "2px solid transparent",
                  marginBottom: "-1px",
                }}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {activeTab === "general" && (
            <GeneralTab operator={operator} loading={loading} />
          )}

          {activeTab === "providers" && (
            <ProvidersTab
              providers={providers}
              loading={loading}
              editing={editing}
              addingPreset={addingPreset}
              showCustom={showCustom}
              onAddPreset={setAddingPreset}
              onShowCustom={setShowCustom}
              onEdit={setEditing}
              onCancelEdit={() => setEditing(null)}
              onSavedPreset={() => { setAddingPreset(null); load(); }}
              onSavedCustom={() => { setShowCustom(false); load(); }}
              onCancelPreset={() => setAddingPreset(null)}
              onCancelCustom={() => setShowCustom(false)}
              onDelete={handleDelete}
            />
          )}

          {activeTab === "models" && (
            <ModelsTab providers={providers} loading={loading} onChanged={load} />
          )}

          {activeTab === "about" && <AboutTab />}
        </div>
      </div>
    </div>
  );
}

function GeneralTab({ operator, loading }: { operator: Operator | null; loading: boolean }) {
  return (
    <div className="max-w-2xl space-y-6">
      {/* Operator profile */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">Operator</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          {loading ? (
            <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>
          ) : operator ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-full text-[14px] font-semibold"
                  style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
                >
                  {operator.username.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="text-[14px] font-medium text-[var(--ink)]">{operator.username}</p>
                  <p className="text-[12px] text-[var(--ink-3)]">Administrator</p>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-[13px] text-[var(--ink-2)]">Not logged in</p>
          )}
        </div>
      </div>

      {/* Appearance */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">Appearance</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] font-medium text-[var(--ink)]">Theme</p>
              <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">Dark mode (only option for now)</p>
            </div>
            <span
              className="rounded-full px-3 py-1 text-[11px] font-medium"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              Dark
            </span>
          </div>
        </div>
      </div>

      {/* Search provider */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">Search Provider</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] font-medium text-[var(--ink)]">Web Search Engine</p>
              <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">Used by the web_search capability</p>
            </div>
            <span
              className="rounded-full px-3 py-1 text-[11px] font-medium"
              style={{ background: "var(--border)", color: "var(--ink-2)" }}
            >
              DuckDuckGo
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProvidersTab({
  providers,
  loading,
  editing,
  addingPreset,
  showCustom,
  onAddPreset,
  onShowCustom,
  onEdit,
  onCancelEdit,
  onSavedPreset,
  onSavedCustom,
  onCancelPreset,
  onCancelCustom,
  onDelete,
}: {
  providers: Provider[];
  loading: boolean;
  editing: string | null;
  addingPreset: number | null;
  showCustom: boolean;
  onAddPreset: (index: number | null) => void;
  onShowCustom: (show: boolean) => void;
  onEdit: (id: string) => void;
  onCancelEdit: () => void;
  onSavedPreset: () => void;
  onSavedCustom: () => void;
  onCancelPreset: () => void;
  onCancelCustom: () => void;
  onDelete: (id: string) => void;
}) {
  // Find which presets are already configured.
  // Match by type AND base_url to distinguish OpenAI-native from OpenAI-compatible presets.
  const isPresetConfigured = (preset: typeof PRESET_PROVIDERS[number]) => {
    return providers.some(
      (p) => p.type === preset.type && (p.base_url || "") === (preset.defaultBaseUrl || ""),
    );
  };

  return (
    <div className="max-w-3xl">
      {/* Configured providers */}
      {providers.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-[13px] font-medium text-[var(--ink-3)] uppercase tracking-wide">Configured</h2>
          <div className="space-y-3">
            {providers.map((p) => (
              <ProviderCard
                key={p.id}
                provider={p}
                editing={editing === p.id}
                onEdit={() => onEdit(p.id)}
                onCancelEdit={onCancelEdit}
                onSaved={() => { onCancelEdit(); onSavedPreset(); }}
                onDelete={() => onDelete(p.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Preset provider grid */}
      {addingPreset === null && !showCustom && (
        <div>
          <h2 className="mb-3 text-[13px] font-medium text-[var(--ink-3)] uppercase tracking-wide">Add a provider</h2>
          {loading ? (
            <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>
          ) : (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              {PRESET_PROVIDERS.map((preset, idx) => {
                const isConfigured = isPresetConfigured(preset);
                return (
                  <button
                    key={idx}
                    onClick={() => onAddPreset(idx)}
                    disabled={isConfigured}
                    className="flex flex-col items-start gap-1 rounded-lg border p-4 text-left transition"
                    style={{
                      borderColor: isConfigured ? "var(--border)" : "var(--border)",
                      background: isConfigured ? "var(--surface)" : "var(--white)",
                      cursor: isConfigured ? "default" : "pointer",
                      opacity: isConfigured ? 0.5 : 1,
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <p className="text-[13px] font-semibold text-[var(--ink)]">{preset.name}</p>
                      {isConfigured && (
                        <Check className="h-3.5 w-3.5" style={{ color: "var(--success)" }} />
                      )}
                    </div>
                    <p className="text-[11px] text-[var(--ink-3)]">{preset.description}</p>
                  </button>
                );
              })}

              {/* Custom provider card */}
              <button
                onClick={() => onShowCustom(true)}
                className="flex flex-col items-start gap-2 rounded-lg border border-dashed p-4 text-left transition"
                style={{ borderColor: "var(--border)", background: "var(--surface)", cursor: "pointer" }}
              >
                <div>
                  <p className="text-[13px] font-semibold text-[var(--ink)]">Custom Provider</p>
                  <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">OpenAI-compatible or other endpoint</p>
                </div>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Preset config form */}
      {addingPreset !== null && (
        <PresetProviderForm
          presetIndex={addingPreset}
          onCancel={onCancelPreset}
          onSaved={onSavedPreset}
        />
      )}

      {/* Custom provider form */}
      {showCustom && (
        <ProviderForm
          onCancel={onCancelCustom}
          onSaved={onSavedCustom}
        />
      )}
    </div>
  );
}

function PresetProviderForm({
  presetIndex,
  onCancel,
  onSaved,
}: {
  presetIndex: number;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const preset = PRESET_PROVIDERS[presetIndex];
  const [name, setName] = useState(preset?.name || "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(preset?.defaultBaseUrl || "");
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createProvider({
        name: name.trim(),
        type: preset.type,
        api_key: apiKey || undefined,
        base_url: baseUrl || null,
      });
      onSaved();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!preset) return null;

  return (
    <div className="max-w-2xl">
      <div className="mb-4">
        <h2 className="text-[15px] font-semibold text-[var(--ink)]">{preset.name}</h2>
        <p className="text-[12px] text-[var(--ink-3)]">{preset.description}</p>
      </div>
      <div
        className="rounded-lg border p-5"
        style={{ borderColor: "var(--border)", background: "var(--white)" }}
      >
        <div className="space-y-3">
          <Field label="Display name">
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }} autoFocus />
          </Field>
          {preset.needsKey && (
            <Field label="API Key">
              <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password"
                placeholder="Paste your API key…"
                className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
            </Field>
          )}
          {(preset.compatOnly || !preset.needsKey) && (
            <Field label="Base URL">
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={preset.defaultBaseUrl || "https://api.example.com/v1"}
                className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
            </Field>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button onClick={handleCreate} disabled={saving || !name.trim()}
              className="flex items-center gap-1.5 rounded-[6px] px-4 py-2 text-[13px] font-medium"
              style={{ background: "var(--ink)", color: "var(--white)", border: "1px solid var(--ink)", cursor: "pointer", opacity: saving || !name.trim() ? 0.5 : 1 }}>
              <Plus className="h-3.5 w-3.5" /> Add
            </button>
            <button onClick={onCancel}
              className="rounded-[6px] px-4 py-2 text-[13px] text-[var(--ink-2)]"
              style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ModelsTab({
  providers,
  loading,
  onChanged,
}: {
  providers: Provider[];
  loading: boolean;
  onChanged: () => void;
}) {
  const [discovered, setDiscovered] = useState<Record<string, ModelInfo[]>>({});
  const [discovering, setDiscovering] = useState<Record<string, boolean>>({});
  const [newModel, setNewModel] = useState<Record<string, string>>({});

  const handleDiscover = async (provider: Provider) => {
    setDiscovering((prev) => ({ ...prev, [provider.id]: true }));
    try {
      const result = await api.listModels(provider.id);
      setDiscovered((prev) => ({ ...prev, [provider.id]: result.models }));
    } catch (e) {
      alert(String(e));
    } finally {
      setDiscovering((prev) => ({ ...prev, [provider.id]: false }));
    }
  };

  const handleAddCustom = async (provider: Provider) => {
    const name = (newModel[provider.id] || "").trim();
    if (!name) return;
    try {
      await api.addCustomModel(provider.id, name);
      setNewModel((prev) => ({ ...prev, [provider.id]: "" }));
      onChanged();
    } catch (e) {
      alert(String(e));
    }
  };

  const handleRemoveCustom = async (provider: Provider, modelName: string) => {
    try {
      await api.removeCustomModel(provider.id, modelName);
      onChanged();
    } catch (e) {
      alert(String(e));
    }
  };

  if (loading) return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;
  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Cpu className="h-8 w-8 text-[var(--ink-3)]" />
        <p className="mt-3 text-[14px] text-[var(--ink-2)]">No providers configured</p>
        <p className="mt-1 text-[12px] text-[var(--ink-3)]">Add a provider first to manage models.</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      {providers.map((provider) => {
        const disc = discovered[provider.id] || [];
        const isDiscovering = discovering[provider.id];
        const custom = provider.custom_models || [];
        return (
          <div
            key={provider.id}
            className="rounded-lg border p-5"
            style={{ borderColor: "var(--border)", background: "var(--white)" }}
          >
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-[14px] font-semibold text-[var(--ink)]">{provider.name}</h3>
                <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
                  {disc.length} discovered · {custom.length} custom
                </p>
              </div>
              <button
                onClick={() => handleDiscover(provider)}
                disabled={isDiscovering}
                className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[12px] text-[var(--ink-2)]"
                style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isDiscovering ? "animate-spin" : ""}`} />
                Discover
              </button>
            </div>

            {/* Discovered models */}
            {disc.length > 0 && (
              <div className="mb-4">
                <p className="mb-2 text-[11px] font-medium text-[var(--ink-3)] uppercase tracking-wide">Discovered</p>
                <div className="flex flex-wrap gap-1.5">
                  {disc.map((m) => (
                    <span
                      key={m.id}
                      className="rounded-full px-2.5 py-1 font-mono text-[11px]"
                      style={{ background: "var(--border)", color: "var(--ink-2)" }}
                    >
                      {m.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Custom models */}
            <div>
              <p className="mb-2 text-[11px] font-medium text-[var(--ink-3)] uppercase tracking-wide">Custom</p>
              {custom.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {custom.map((m) => (
                    <span
                      key={m}
                      className="flex items-center gap-1 rounded-full px-2.5 py-1 font-mono text-[11px]"
                      style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
                      title={`${provider.type}/${m}`}
                    >
                      {m}
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRemoveCustom(provider, m); }}
                        style={{ border: "none", background: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center" }}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <span
                  className="flex items-center rounded-[5px] border px-2.5 py-2 font-mono text-[12px] text-[var(--ink-3)]"
                  style={{ borderColor: "var(--border)", background: "var(--surface)", whiteSpace: "nowrap" }}
                >
                  {provider.type}/
                </span>
                <input
                  value={newModel[provider.id] || ""}
                  onChange={(e) => setNewModel((prev) => ({ ...prev, [provider.id]: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && handleAddCustom(provider)}
                  placeholder="model-name"
                  className="flex-1 rounded-[5px] border px-3 py-2 font-mono text-[12px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                />
                <button
                  onClick={() => handleAddCustom(provider)}
                  disabled={!(newModel[provider.id] || "").trim()}
                  className="flex items-center gap-1 rounded-[5px] px-3 py-2 text-[12px] font-medium"
                  style={{
                    background: "var(--ink)",
                    color: "var(--white)",
                    border: "1px solid var(--ink)",
                    cursor: "pointer",
                    opacity: (newModel[provider.id] || "").trim() ? 1 : 0.5,
                  }}
                >
                  <Plus className="h-3.5 w-3.5" /> Add
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AboutTab() {
  return (
    <div className="max-w-2xl space-y-6">
      {/* Logo + version */}
      <div
        className="flex items-center gap-4 rounded-lg border p-6"
        style={{ borderColor: "var(--border)", background: "var(--white)" }}
      >
        <LogoMark className="h-12 w-12" color="var(--ink)" />
        <div>
          <h2 className="text-[18px] font-semibold text-[var(--ink)]">CaberOS</h2>
          <p className="text-[13px] text-[var(--ink-2)]">Local-first AI Agent Operating System</p>
          <p className="mt-1 font-mono text-[11px] text-[var(--ink-3)]">v0.1.0</p>
        </div>
      </div>

      {/* Tech stack */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">Tech Stack</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-[12px] font-medium text-[var(--ink-3)]">Backend</p>
              <p className="mt-1 text-[13px] text-[var(--ink)]">Python 3.12 · FastAPI · SQLAlchemy · LiteLLM</p>
            </div>
            <div>
              <p className="text-[12px] font-medium text-[var(--ink-3)]">Frontend</p>
              <p className="mt-1 text-[13px] text-[var(--ink)]">React 19 · Vite · Tailwind CSS</p>
            </div>
            <div>
              <p className="text-[12px] font-medium text-[var(--ink-3)]">Database</p>
              <p className="mt-1 text-[13px] text-[var(--ink)]">SQLite (WAL mode)</p>
            </div>
            <div>
              <p className="text-[12px] font-medium text-[var(--ink-3)]">Sandbox</p>
              <p className="mt-1 text-[13px] text-[var(--ink)]">sandbox-exec (macOS) · bubblewrap (Linux)</p>
            </div>
          </div>
        </div>
      </div>

      {/* Links */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">Links</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          <div className="space-y-2">
            <a
              href="https://github.com/caberos/caberos"
              target="_blank"
              rel="noopener noreferrer"
              className="block text-[13px] text-[var(--accent)] hover:underline"
            >
              GitHub Repository →
            </a>
            <a
              href="https://caberos.ai/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="block text-[13px] text-[var(--accent)] hover:underline"
            >
              Documentation →
            </a>
            <a
              href="https://caberos.ai/support"
              target="_blank"
              rel="noopener noreferrer"
              className="block text-[13px] text-[var(--accent)] hover:underline"
            >
              Support →
            </a>
          </div>
        </div>
      </div>

      {/* License */}
      <div>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">License</h2>
        <div
          className="rounded-lg border p-5"
          style={{ borderColor: "var(--border)", background: "var(--white)" }}
        >
          <p className="text-[13px] text-[var(--ink-2)]">
            CaberOS is open-source software. Fonts: Inter (OFL) &amp; JetBrains Mono (Apache 2.0).
          </p>
        </div>
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  editing,
  onEdit,
  onCancelEdit,
  onSaved,
  onDelete,
}: {
  provider: Provider;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSaved: () => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(provider.name);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url || "");
  const [orgId, setOrgId] = useState(provider.org_id || "");
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    setName(provider.name);
    setApiKey("");
    setBaseUrl(provider.base_url || "");
    setOrgId(provider.org_id || "");
  }, [provider]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateProvider(provider.id, {
        name,
        base_url: baseUrl || null,
        org_id: orgId || null,
        ...(apiKey ? { api_key: apiKey } : {}),
      });
      onSaved();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscover = async () => {
    setLoadingModels(true);
    try {
      const result = await api.listModels(provider.id);
      setModels(result.models);
    } catch (e) {
      alert(String(e));
    } finally {
      setLoadingModels(false);
    }
  };

  if (editing) {
    return (
      <div
        className="rounded-lg border p-5"
        style={{ borderColor: "var(--border)", background: "var(--white)" }}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-[var(--ink)]">Edit {provider.type}</h3>
          <button onClick={onCancelEdit} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--ink-3)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
          </Field>
          <Field label={`API Key${provider.has_key ? " (leave blank to keep current)" : ""}`}>
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password"
              placeholder={provider.has_key ? "••••••••" : "sk-..."}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Base URL (optional)">
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
            </Field>
            <Field label="Org ID (optional)">
              <input value={orgId} onChange={(e) => setOrgId(e.target.value)}
                className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
            </Field>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button onClick={handleSave} disabled={saving}
              className="flex items-center gap-1.5 rounded-[6px] px-4 py-2 text-[13px] font-medium"
              style={{ background: "var(--ink)", color: "var(--white)", border: "1px solid var(--ink)", cursor: "pointer", opacity: saving ? 0.5 : 1 }}>
              <Save className="h-3.5 w-3.5" /> Save
            </button>
            <button onClick={handleDiscover} disabled={loadingModels}
              className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-[var(--ink-2)]"
              style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}>
              <RefreshCw className={`h-3.5 w-3.5 ${loadingModels ? "animate-spin" : ""}`} /> Discover Models
            </button>
          </div>
          {models && (
            <div className="rounded-[5px] border p-3" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
              <p className="mb-2 text-[12px] font-medium text-[var(--ink-2)]">
                Available models ({models.length})
              </p>
              <div className="flex flex-wrap gap-1.5">
                {models.map((m) => (
                  <span key={m.id} className="rounded-full px-2.5 py-1 font-mono text-[11px]"
                    style={{ background: "var(--border)", color: "var(--ink-2)" }}>
                    {m.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex items-center justify-between rounded-lg border p-5"
      style={{ borderColor: "var(--border)", background: "var(--white)" }}
    >
      <div className="flex items-center gap-3">
        <div>
          <h3 className="text-[14px] font-semibold text-[var(--ink)]">{provider.name}</h3>
          <div className="mt-0.5 flex items-center gap-2">
            {provider.has_key && (
              <span className="flex items-center gap-0.5 text-[11px]" style={{ color: "var(--success)" }}>
                <Check className="h-3 w-3" /> key set
              </span>
            )}
            {provider.base_url && (
              <span className="font-mono text-[11px] text-[var(--ink-3)]">{provider.base_url}</span>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button onClick={onEdit}
          className="rounded-[5px] px-3 py-1.5 text-[12px] text-[var(--ink-2)] transition"
          style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}>
          Edit
        </button>
        <button onClick={onDelete}
          className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-3)] transition hover:text-[var(--danger)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}>
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function ProviderForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createProvider({
        name: name.trim(),
        type,
        api_key: apiKey || undefined,
        base_url: baseUrl || null,
      });
      onSaved();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="rounded-lg border p-5"
      style={{ borderColor: "var(--accent)", background: "var(--white)" }}
    >
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-[14px] font-semibold text-[var(--ink)]">Add Provider</h3>
        <button onClick={onCancel} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--ink-3)" }}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My OpenAI"
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }} autoFocus />
          </Field>
          <Field label="Type">
            <select value={type} onChange={(e) => setType(e.target.value)}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
              {["openai", "anthropic", "gemini", "google", "ollama", "azure", "mistral", "cohere", "bedrock", "huggingface", "nvidia_nim", "ai21", "together_ai", "groq", "perplexity", "fireworks_ai", "dashscope", "moonshot", "zhipu", "minimax", "deepseek", "openrouter", "xai"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
        </div>
        <Field label="API Key">
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password" placeholder="sk-..."
            className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
        </Field>
        <Field label="Base URL (optional, for Ollama or custom endpoints)">
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:11434"
            className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }} />
        </Field>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={handleCreate} disabled={saving || !name.trim()}
            className="flex items-center gap-1.5 rounded-[6px] px-4 py-2 text-[13px] font-medium"
            style={{ background: "var(--ink)", color: "var(--white)", border: "1px solid var(--ink)", cursor: "pointer", opacity: saving || !name.trim() ? 0.5 : 1 }}>
            <Plus className="h-3.5 w-3.5" /> Add
          </button>
          <button onClick={onCancel}
            className="rounded-[6px] px-4 py-2 text-[13px] text-[var(--ink-2)]"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">{label}</label>
      {children}
    </div>
  );
}
