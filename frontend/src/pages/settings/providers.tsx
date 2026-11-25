import { useEffect, useState } from "react";
import {
  Check,
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { Provider } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { Field, ProviderTile } from "./shared";

// Preset providers — known services with sensible defaults
interface ProviderPreset {
  type: string;
  name: string;
  description: string;
  defaultBaseUrl: string;
  needsKey: boolean;
  compatOnly?: boolean;
  // Page grouping — defaults to "cloud".
  group?: "local" | "cloud" | "enterprise";
}

const PRESET_PROVIDERS: ProviderPreset[] = [
  {
    type: "openai",
    name: "OpenAI",
    description: "GPT-4o, o1, o3, and more",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "anthropic",
    name: "Anthropic",
    description: "Claude 3.5 Sonnet, Opus, Haiku",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "gemini",
    name: "Google Gemini",
    description: "Gemini 2.0 Flash, Pro, and more",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "deepseek",
    name: "DeepSeek",
    description: "DeepSeek V3, R1, Coder",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "openrouter",
    name: "OpenRouter",
    description: "Multi-provider routing — 300+ models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "fireworks_ai",
    name: "Fireworks AI",
    description: "OpenAI-compatible model API",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "xai",
    name: "xAI (Grok)",
    description: "Grok models via direct API",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "mistral",
    name: "Mistral AI",
    description: "Mistral Large, Codestral, and more",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "ollama",
    name: "Ollama (Local)",
    description: "Run models locally — Llama, Qwen, etc.",
    defaultBaseUrl: "http://localhost:11434",
    needsKey: false,
    group: "local",
  },
  {
    type: "azure",
    name: "Azure OpenAI",
    description: "Enterprise OpenAI via Azure",
    defaultBaseUrl: "",
    needsKey: true,
    group: "enterprise",
  },
  {
    type: "bedrock",
    name: "AWS Bedrock",
    description: "Claude, Nova, Llama via Converse API",
    defaultBaseUrl: "",
    needsKey: true,
    group: "enterprise",
  },
  {
    type: "huggingface",
    name: "Hugging Face",
    description: "20+ open models via unified router",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "nvidia_nim",
    name: "NVIDIA NIM",
    description: "Nemotron models via build.nvidia.com",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "cohere",
    name: "Cohere",
    description: "Command R+, Aya, and more",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "ai21",
    name: "AI21 Labs",
    description: "Jamba models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "together_ai",
    name: "Together AI",
    description: "Open models on fast inference",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "groq",
    name: "Groq",
    description: "Ultra-fast inference for open models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "perplexity",
    name: "Perplexity",
    description: "Perplexity Online/Sonar models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "dashscope",
    name: "Alibaba (Qwen)",
    description: "Qwen models via DashScope",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "moonshot",
    name: "Moonshot (Kimi)",
    description: "Kimi coding and chat models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "zhipu",
    name: "Z.AI (GLM)",
    description: "GLM / Zhipu-hosted models",
    defaultBaseUrl: "",
    needsKey: true,
  },
  {
    type: "minimax",
    name: "MiniMax",
    description: "MiniMax frontier model",
    defaultBaseUrl: "",
    needsKey: true,
  },
  // OpenAI-compatible endpoints (use type "openai" with custom base_url)
  {
    type: "openai",
    name: "NovitaAI",
    description: "Multi-model API gateway",
    defaultBaseUrl: "https://api.novita.ai/v1",
    needsKey: true,
    compatOnly: true,
  },
  {
    type: "openai",
    name: "LM Studio (Local)",
    description: "Local desktop app, OpenAI-compatible",
    defaultBaseUrl: "http://localhost:1234/v1",
    needsKey: false,
    compatOnly: true,
    group: "local",
  },
  {
    type: "openai",
    name: "Vercel AI Gateway",
    description: "Vercel AI Gateway routing",
    defaultBaseUrl: "https://ai-gateway.vercel.sh/v1",
    needsKey: true,
    compatOnly: true,
  },
  {
    type: "openai",
    name: "vLLM / SGLang",
    description: "Self-hosted OpenAI-compatible server",
    defaultBaseUrl: "http://localhost:8000/v1",
    needsKey: false,
    compatOnly: true,
    group: "local",
  },
  {
    type: "openai",
    name: "OpenCode Zen",
    description: "Pay-per-use — GPT-5.x, Claude, Gemini, open models",
    defaultBaseUrl: "https://opencode.ai/zen/v1",
    needsKey: true,
    compatOnly: true,
  },
  {
    type: "openai",
    name: "OpenCode Go",
    description: "$10/mo subscription — GLM, Kimi, DeepSeek, MiMo",
    defaultBaseUrl: "https://opencode.ai/zen/go/v1",
    needsKey: true,
    compatOnly: true,
  },
  {
    type: "openai",
    name: "Ollama Cloud",
    description: "Hosted Ollama — gpt-oss, kimi-k2, llama4, and more",
    defaultBaseUrl: "https://ollama.com/v1",
    needsKey: true,
    compatOnly: true,
  },
];

type ProviderModal =
  | { kind: "preset"; index: number }
  | { kind: "custom" }
  | { kind: "edit"; provider: Provider }
  | null;

/** Extra fields some provider types need beyond a single API key.
 *  Secrets land in `credentials` (Fernet-encrypted), never extra_params.
 *  `hideKey`/`baseUrl:false` reshape the generic fields when the type
 *  authenticates differently (bedrock has no single API key). */
interface CredentialFieldSpec {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
}
const PROVIDER_FIELD_SPEC: Record<
  string,
  {
    hideKey?: boolean;
    baseUrl?: { label: string; placeholder: string } | false;
    credentials: CredentialFieldSpec[];
  }
> = {
  azure: {
    baseUrl: {
      label: "Endpoint",
      placeholder: "https://<resource>.openai.azure.com/",
    },
    credentials: [
      { key: "api_version", label: "API version", placeholder: "2024-10-21" },
    ],
  },
  bedrock: {
    hideKey: true,
    baseUrl: false,
    credentials: [
      { key: "aws_access_key_id", label: "AWS access key ID", secret: true },
      {
        key: "aws_secret_access_key",
        label: "AWS secret access key",
        secret: true,
      },
      { key: "aws_region_name", label: "AWS region", placeholder: "us-east-1" },
      {
        key: "aws_session_token",
        label: "AWS session token (optional)",
        secret: true,
      },
    ],
  },
};

const CUSTOM_PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "gemini",
  "google",
  "ollama",
  "azure",
  "mistral",
  "cohere",
  "bedrock",
  "huggingface",
  "nvidia_nim",
  "ai21",
  "together_ai",
  "groq",
  "perplexity",
  "fireworks_ai",
  "dashscope",
  "moonshot",
  "zhipu",
  "minimax",
  "deepseek",
  "openrouter",
  "xai",
];


function presetGroup(p: ProviderPreset) {
  return p.group ?? "cloud";
}

export function ProvidersTab({
  providers,
  loading,
  onChanged,
  onDelete,
}: {
  providers: Provider[];
  loading: boolean;
  onChanged: () => void;
  onDelete: (id: string) => void;
}) {
  const [modal, setModal] = useState<ProviderModal>(null);
  const [query, setQuery] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const { toast } = useConfirm();

  // Multiple providers of the same type are allowed (e.g. several OpenAI
  // keys) — match a preset by type AND base_url so OpenAI-native and
  // OpenAI-compatible presets count separately.
  const presetCount = (preset: ProviderPreset) =>
    providers.filter(
      (p) =>
        p.type === preset.type &&
        (p.base_url || "") === (preset.defaultBaseUrl || ""),
    ).length;

  const q = query.trim().toLowerCase();
  const presetVisible = (p: ProviderPreset) =>
    !q ||
    p.name.toLowerCase().includes(q) ||
    p.description.toLowerCase().includes(q);
  const groupPresets = (g: "local" | "cloud" | "enterprise") =>
    PRESET_PROVIDERS.map((preset, index) => ({ preset, index })).filter(
      ({ preset }) => presetGroup(preset) === g && presetVisible(preset),
    );
  const connected = providers.filter(
    (p) => !q || p.name.toLowerCase().includes(q),
  );
  const groups = {
    local: groupPresets("local"),
    cloud: groupPresets("cloud"),
    enterprise: groupPresets("enterprise"),
  };
  const showConnected = connected.length > 0;

  // Live connectivity check: the scheduled discovery job fetches the
  // provider's real model list — auth + reachability without a paid probe.
  const testConnection = async (p: Provider) => {
    setTesting(p.id);
    try {
      await api.refreshProviderModels(p.id).catch(() => null);
      for (let i = 0; i < 30; i++) {
        const r = await api.listModels(p.id);
        if (!r.refresh_in_progress) {
          const err = r.models.find((m) => m.discovery_error)?.discovery_error;
          toast(
            err
              ? `Connection failed: ${err}`
              : `Connected — ${r.models.length} model${r.models.length === 1 ? "" : "s"} reachable`,
          );
          return;
        }
        await new Promise((res) => setTimeout(res, 1000));
      }
      toast("Still checking — watch the Models tab for the result");
    } catch (e) {
      toast(`Connection failed: ${e}`);
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="max-w-4xl space-y-8">
      <div className="relative max-w-xs">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--ink-3)]" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search providers"
          className="w-full rounded-lg border bg-[var(--surface)] py-2 pl-9 pr-3 text-[13px] text-[var(--ink)] outline-none transition placeholder:text-[var(--ink-3)] focus:border-[var(--accent)]"
          style={{ borderColor: "var(--border)" }}
        />
      </div>
      {/* Connected */}
      {showConnected && (
        <section id="connected">
          <h2 className="text-[14px] font-semibold text-[var(--ink)]">
            Connected
          </h2>
          <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
            {connected.length} provider{connected.length === 1 ? "" : "s"} are
            ready to use.
          </p>
          <div className="space-y-2.5">
            {connected.map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-3.5 rounded-xl border px-4 py-3.5"
                style={{
                  borderColor: "var(--border-soft)",
                  background: "var(--surface)",
                }}
              >
                <ProviderTile name={p.name} />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold text-[var(--ink)]">
                    {p.name}
                  </p>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                    {p.has_key ? (
                      <span
                        className="flex items-center gap-1"
                        style={{ color: "var(--success)" }}
                      >
                        ● API key set
                      </span>
                    ) : (
                      <span className="text-[var(--ink-3)]">No API key</span>
                    )}
                    {p.base_url && (
                      <span className="truncate font-mono text-[var(--ink-3)]">
                        {p.base_url}
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => void testConnection(p)}
                  disabled={testing === p.id}
                  className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                  style={{ borderColor: "var(--border)" }}
                >
                  <Play
                    className={`h-3 w-3 ${testing === p.id ? "animate-pulse" : ""}`}
                  />
                  {testing === p.id ? "Testing…" : "Test connection"}
                </button>
                <button
                  onClick={() => setModal({ kind: "edit", provider: p })}
                  className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                  style={{ borderColor: "var(--border)" }}
                >
                  <Pencil className="h-3 w-3" />
                  Edit
                </button>
                <div className="relative">
                  <button
                    onClick={() => setMenuFor(menuFor === p.id ? null : p.id)}
                    aria-label={`${p.name} actions`}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--ink-3)] transition hover:bg-[var(--hover)] hover:text-[var(--ink)]"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {menuFor === p.id && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setMenuFor(null)}
                      />
                      <div
                        className="absolute right-0 top-8 z-20 w-44 overflow-hidden rounded-lg border py-1 shadow-lg"
                        style={{
                          borderColor: "var(--border)",
                          background: "var(--surface)",
                        }}
                      >
                        <button
                          onClick={() => {
                            setMenuFor(null);
                            onDelete(p.id);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-[var(--danger)] transition hover:bg-[var(--hover)]"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Remove provider
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {loading && <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>}

      {/* Local */}
      {groups.local.length > 0 && (
        <section id="local">
          <h2 className="text-[14px] font-semibold text-[var(--ink)]">Local</h2>
          <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
            Best fit for a local-first setup.
          </p>
          <div className="space-y-2.5">
            {groups.local.map(({ preset, index }) => (
              <PresetConnectCard
                key={index}
                preset={preset}
                count={presetCount(preset)}
                wide
                onConnect={() => setModal({ kind: "preset", index })}
              />
            ))}
          </div>
        </section>
      )}

      {/* Cloud APIs */}
      {groups.cloud.length > 0 && (
        <section id="cloud">
          <h2 className="text-[14px] font-semibold text-[var(--ink)]">
            Cloud APIs
          </h2>
          <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
            Bring your own API key.
          </p>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {groups.cloud.map(({ preset, index }) => (
              <PresetConnectCard
                key={index}
                preset={preset}
                count={presetCount(preset)}
                onConnect={() => setModal({ kind: "preset", index })}
              />
            ))}
            <button
              onClick={() => setModal({ kind: "custom" })}
              className="flex items-center gap-3.5 rounded-xl border border-dashed px-4 py-3.5 text-left transition hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)" }}
            >
              <span
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-[var(--ink-3)]"
                style={{ border: "1px dashed var(--border)" }}
              >
                <Plus className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-semibold text-[var(--ink)]">
                  Custom provider
                </p>
                <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">
                  OpenAI-compatible or other endpoint
                </p>
              </div>
            </button>
          </div>
        </section>
      )}

      {/* Enterprise */}
      {groups.enterprise.length > 0 && (
        <section id="enterprise">
          <h2 className="text-[14px] font-semibold text-[var(--ink)]">
            Enterprise
          </h2>
          <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
            For teams already on a cloud account.
          </p>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {groups.enterprise.map(({ preset, index }) => (
              <PresetConnectCard
                key={index}
                preset={preset}
                count={presetCount(preset)}
                onConnect={() => setModal({ kind: "preset", index })}
              />
            ))}
          </div>
        </section>
      )}

      {!loading &&
        !showConnected &&
        groups.local.length === 0 &&
        groups.cloud.length === 0 &&
        groups.enterprise.length === 0 && (
          <p className="py-10 text-center text-[13px] text-[var(--ink-3)]">
            No providers match "{query}"
          </p>
        )}

      {modal && (
        <ProviderSetupModal
          modal={modal}
          providers={providers}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}


function PresetConnectCard({
  preset,
  count,
  wide,
  onConnect,
}: {
  preset: ProviderPreset;
  count: number;
  wide?: boolean;
  onConnect: () => void;
}) {
  return (
    <div
      className="flex items-center gap-3.5 rounded-xl border px-4 py-3.5"
      style={{
        borderColor: "var(--border-soft)",
        background: "var(--surface)",
      }}
    >
      <ProviderTile name={preset.name} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-[13px] font-semibold text-[var(--ink)]">
            {preset.name}
          </p>
          {presetGroup(preset) === "local" && (
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              Local
            </span>
          )}
          {count > 0 && (
            <span
              className="flex items-center gap-1 text-[10px] font-medium"
              style={{ color: "var(--success)" }}
            >
              <Check className="h-3 w-3" />
              {count === 1 ? "Added" : `Added ×${count}`}
            </span>
          )}
        </div>
        <p
          className={`mt-0.5 text-[11px] text-[var(--ink-3)] ${wide ? "" : "line-clamp-2"}`}
        >
          {preset.description}
        </p>
      </div>
      <button
        onClick={onConnect}
        className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition"
        style={
          wide
            ? {
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
              }
            : {
                border: "1px solid var(--border)",
                color: "var(--ink-2)",
              }
        }
      >
        <Plus className="h-3.5 w-3.5" />
        Connect
      </button>
    </div>
  );
}

function ProviderSetupModal({
  modal,
  providers,
  onClose,
  onSaved,
}: {
  modal: NonNullable<ProviderModal>;
  providers: Provider[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const preset = modal.kind === "preset" ? PRESET_PROVIDERS[modal.index] : null;
  const editing = modal.kind === "edit" ? modal.provider : null;
  const existing = preset
    ? providers.filter(
        (p) =>
          p.type === preset.type &&
          (p.base_url || "") === (preset.defaultBaseUrl || ""),
      ).length
    : 0;
  const [name, setName] = useState(
    editing?.name ??
      (preset
        ? existing > 0
          ? `${preset.name} ${existing + 1}`
          : preset.name
        : ""),
  );
  const [type, setType] = useState(editing?.type ?? preset?.type ?? "openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(
    editing?.base_url ?? preset?.defaultBaseUrl ?? "",
  );
  const [orgId, setOrgId] = useState(editing?.org_id ?? "");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const { toast } = useConfirm();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const fieldSpec = PROVIDER_FIELD_SPEC[type];
  const showKey = fieldSpec?.hideKey
    ? false
    : preset
      ? preset.needsKey
      : true;
  const showBaseUrl =
    fieldSpec?.baseUrl === false
      ? false
      : fieldSpec?.baseUrl
        ? true
        : preset
          ? preset.compatOnly || !preset.needsKey
          : true;
  const title = editing
    ? `${editing.name} settings`
    : preset
      ? `Connect ${preset.name}`
      : "Custom provider";
  const tileName = editing?.name ?? preset?.name ?? "+";

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      // Blank credential fields keep the stored value on update; only
      // non-empty inputs for the CURRENT type's fields are sent.
      const credPayload = Object.fromEntries(
        (fieldSpec?.credentials ?? [])
          .map((f) => [f.key, (creds[f.key] ?? "").trim()] as const)
          .filter(([, v]) => v),
      );
      const credentials =
        Object.keys(credPayload).length > 0 ? credPayload : undefined;
      if (editing) {
        await api.updateProvider(editing.id, {
          name: name.trim(),
          base_url: baseUrl || null,
          org_id: orgId || null,
          ...(apiKey ? { api_key: apiKey } : {}),
          ...(credentials ? { credentials } : {}),
        });
      } else {
        await api.createProvider({
          name: name.trim(),
          type,
          api_key: apiKey || undefined,
          base_url: baseUrl || null,
          ...(credentials ? { credentials } : {}),
        });
      }
      onSaved();
    } catch (e) {
      toast(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-[440px] flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{ borderColor: "var(--line)", background: "var(--surface)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between border-b px-5 py-3.5"
          style={{ borderColor: "var(--line)" }}
        >
          <div className="flex items-center gap-2.5">
            {modal.kind === "custom" ? (
              <span
                className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--ink-3)]"
                style={{ border: "1px dashed var(--border)" }}
              >
                <Plus className="h-3.5 w-3.5" />
              </span>
            ) : (
              <span
                className="flex h-7 w-7 items-center justify-center rounded-md text-[12px] font-semibold"
                style={{
                  background: "var(--accent-bg)",
                  color: "var(--accent)",
                }}
              >
                {tileName.charAt(0).toUpperCase()}
              </span>
            )}
            <h3 className="text-[14px] font-semibold text-[var(--ink)]">
              {title}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[var(--ink-3)] transition hover:bg-[var(--sunken)] hover:text-[var(--ink)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-3.5">
            {preset?.description && (
              <p className="text-[12px] text-[var(--ink-3)]">
                {preset.description}
              </p>
            )}
            <Field label="Display name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
                className="w-full rounded-lg border px-3 py-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                }}
              />
            </Field>
            {modal.kind === "custom" && (
              <Field label="Type">
                <Select
                  value={type}
                  onChange={setType}
                  options={CUSTOM_PROVIDER_TYPES.map((t) => ({ value: t, label: t }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-surface px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  align="left" panelClassName="text-[13px]"
                />
              </Field>
            )}
            {showKey && (
              <Field
                label={`API Key${editing?.has_key ? " (leave blank to keep current)" : ""}`}
              >
                <input
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  type="password"
                  placeholder={
                    editing?.has_key ? "••••••••" : "Paste your API key…"
                  }
                  className="w-full rounded-lg border px-3 py-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                  }}
                />
              </Field>
            )}
            {showBaseUrl && (
              <Field label={fieldSpec?.baseUrl ? fieldSpec.baseUrl.label : "Base URL"}>
                <input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={
                    (fieldSpec?.baseUrl ? fieldSpec.baseUrl.placeholder : "") ||
                    preset?.defaultBaseUrl ||
                    "https://api.example.com/v1"
                  }
                  className="w-full rounded-lg border px-3 py-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                  }}
                />
              </Field>
            )}
            {fieldSpec?.credentials.map((f) => (
              <Field
                key={f.key}
                label={`${f.label}${
                  editing?.credential_fields.includes(f.key)
                    ? " (leave blank to keep current)"
                    : ""
                }`}
              >
                <input
                  value={creds[f.key] ?? ""}
                  onChange={(e) =>
                    setCreds((c) => ({ ...c, [f.key]: e.target.value }))
                  }
                  type={f.secret ? "password" : "text"}
                  placeholder={
                    editing?.credential_fields.includes(f.key)
                      ? "••••••••"
                      : f.placeholder
                  }
                  className={`w-full rounded-lg border px-3 py-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)] ${
                    f.secret ? "font-mono text-[12px]" : ""
                  }`}
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                  }}
                />
              </Field>
            ))}
            {(modal.kind === "custom" || editing) && (
              <Field label="Org ID (optional)">
                <input
                  value={orgId}
                  onChange={(e) => setOrgId(e.target.value)}
                  className="w-full rounded-lg border px-3 py-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                  }}
                />
              </Field>
            )}
          </div>
        </div>

        <div
          className="flex justify-end gap-2 border-t px-5 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          <button
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-[13px] text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
            style={{ border: "1px solid var(--border)" }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-medium disabled:opacity-50"
            style={{
              background: "var(--ink)",
              color: "var(--white)",
              border: "1px solid var(--ink)",
            }}
          >
            {editing ? (
              <Save className="h-3.5 w-3.5" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            {editing ? "Save" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
