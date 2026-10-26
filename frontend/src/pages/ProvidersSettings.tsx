import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Plus,
  Trash2,
  Save,
  X,
  RefreshCw,
  Check,
  Info,
  Settings,
  Server,
  Cpu,
  Download,
  Upload,
  HardDrive,
  Globe,
  Play,
  Pencil,
  MoreHorizontal,
  Search,
  ClipboardCopy,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { openUrl } from "@/lib/openUrl";
import { CHROME_PATH_EXAMPLE } from "@/lib/platform";
import type { Agent, Provider, ModelInfo, Operator } from "@/lib/types";
import {
  downloadAndInstallUpdate,
  isDesktopMode,
  refreshUpdates,
  restartApp,
  resetUpdater,
  useUpdater,
} from "@/lib/updater";
import {
  DashboardSidebar,
  NAV_ROUTES,
  type NavKey,
} from "@/components/DashboardSidebar";
import { PageHeader } from "@/components/ui/page-header";
import { FilterPills } from "@/components/ui/filter-pills";
import { LogoMark } from "@/components/LogoMark";
import type { ThemeMode } from "@/lib/theme";
import { useTheme } from "@/lib/themeHook";
import {
  resetGuidance,
  resetIntroFlags,
  setTourState,
} from "@/components/guidance/guidanceState";
import { NotificationPrefsForm } from "@/components/NotificationPrefsForm";
import { OptionalToolsAndRuntimes } from "@/components/OptionalToolsAndRuntimes";
import { ContextCaptureSettings } from "@/components/ContextCaptureSettings";
import { Select } from "@/components/ui/select";

// Open URLs in the system browser when running inside Tauri,
// fall back to normal browser navigation otherwise.
async function openExternal(e: React.MouseEvent<HTMLAnchorElement>) {
  const href = e.currentTarget.href;
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    e.preventDefault();
    await openUrl(href);
  }
}

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

type SettingsTab =
  "general" | "providers" | "models" | "browser" | "migration" | "about";

const SETTINGS_TABS: SettingsTab[] = [
  "general", "providers", "models", "browser", "migration", "about",
];

export function ProvidersSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [operator, setOperator] = useState<Operator | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchParams] = useSearchParams();
  const initialTab = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    SETTINGS_TABS.includes(initialTab as SettingsTab)
      ? (initialTab as SettingsTab)
      : "general",
  );
  const navigate = useNavigate();
  const { confirm, toast } = useConfirm();

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

  useEffect(() => {
    load();
  }, [load]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {}
    window.location.assign("/login");
  };

  const handleNavigate = (page: NavKey) => {
    navigate(NAV_ROUTES[page]);
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: "Delete provider?",
      message: "Agents using it will need to be reconfigured.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteProvider(id);
      load();
    } catch (e) {
      toast(String(e));
    }
  };

  const tabs: { key: SettingsTab; label: string; icon: typeof Settings }[] = [
    { key: "general", label: "General", icon: Settings },
    { key: "providers", label: "Providers", icon: Server },
    { key: "models", label: "Models", icon: Cpu },
    { key: "browser", label: "Browser", icon: Globe },
    { key: "migration", label: "Migration", icon: HardDrive },
    { key: "about", label: "About", icon: Info },
  ];

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: "var(--ground)" }}
    >
      <DashboardSidebar
        active="settings"
        onNavigate={handleNavigate}
        onLogout={handleLogout}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          breadcrumbs={[
            { label: "Settings" },
            {
              label: tabs.find((t) => t.key === activeTab)?.label ?? "General",
            },
          ]}
          title="Settings"
          subtitle="Manage your CaberOS configuration."
        />

        {/* Tabs */}
        <div className="px-8 pb-3">
          <FilterPills
            pills={tabs.map((t) => ({ key: t.key, label: t.label }))}
            active={activeTab}
            onChange={(k) => setActiveTab(k as SettingsTab)}
            variant="segmented"
          />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {activeTab === "general" && (
            <GeneralTab
              operator={operator}
              loading={loading}
              onLogout={handleLogout}
              onOperatorChanged={setOperator}
            />
          )}

          {activeTab === "providers" && (
            <ProvidersTab
              providers={providers}
              loading={loading}
              onChanged={load}
              onDelete={handleDelete}
            />
          )}

          {activeTab === "models" && (
            <ModelsTab
              providers={providers}
              loading={loading}
              onChanged={load}
            />
          )}

          {activeTab === "browser" && <BrowserTab />}

          {activeTab === "migration" && <MigrationTab />}

          {activeTab === "about" && <AboutTab />}
        </div>
      </div>
    </div>
  );
}

function SettingsSection({
  id,
  title,
  subtitle,
  children,
}: {
  id: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id}>
      <h2 className="text-[14px] font-semibold text-[var(--ink)]">{title}</h2>
      <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">{subtitle}</p>
      <div
        className="rounded-xl p-5"
        style={{
          border: "1px solid var(--border-soft)",
          background: "var(--surface)",
        }}
      >
        {children}
      </div>
    </section>
  );
}

function GeneralTab({
  operator,
  loading,
  onLogout,
  onOperatorChanged,
}: {
  operator: Operator | null;
  loading: boolean;
  onLogout: () => void;
  onOperatorChanged: (op: Operator) => void;
}) {
  const { mode, setMode, resolvedTheme } = useTheme();

  return (
    <div className="max-w-4xl space-y-6">
      <SettingsSection
        id="operator"
        title="Operator"
        subtitle="The account running this workspace."
      >
        {loading ? (
          <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>
        ) : operator ? (
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-lg text-[14px] font-semibold"
                style={{
                  background: "var(--accent-bg)",
                  color: "var(--accent)",
                }}
              >
                {operator.username.charAt(0).toUpperCase()}
              </div>
              <div>
                <p className="text-[14px] font-medium text-[var(--ink)]">
                  {operator.username}
                </p>
                <p className="text-[12px] text-[var(--ink-3)]">Administrator</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)", color: "var(--ink)" }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <p className="text-[13px] text-[var(--ink-2)]">Not logged in</p>
        )}
      </SettingsSection>

      {operator && (
        <SettingsSection
          id="sign-in"
          title="Sign-in"
          subtitle={
            operator.must_change_password
              ? "This workspace still uses the default login — set your own."
              : "Change the password used to open this workspace."
          }
        >
          <CredentialsForm operator={operator} onChanged={onOperatorChanged} />
        </SettingsSection>
      )}

      <SettingsSection
        id="appearance"
        title="Appearance"
        subtitle="Pick how CaberOS looks."
      >
        <ThemeSwatches mode={mode} onChange={setMode} />
        <p className="mt-3 text-[12px] text-[var(--ink-3)]">
          System follows your operating-system setting. Currently using{" "}
          {resolvedTheme} mode.
        </p>
        <HintReset />
      </SettingsSection>

      <SettingsSection
        id="notifications"
        title="Notifications"
        subtitle="Choose what alerts you and when."
      >
        <NotificationPrefsForm />
      </SettingsSection>

      <SettingsSection
        id="capture"
        title="Request Capture"
        subtitle="How long model request and response bodies are kept."
      >
        <ContextCaptureSettings />
      </SettingsSection>

      <SettingsSection
        id="search"
        title="Search"
        subtitle="Which engine answers agent web searches."
      >
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px] font-medium text-[var(--ink)]">
              Web search engine
            </p>
            <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
              Used by the web_search capability
            </p>
          </div>
          <span
            className="rounded-full px-3 py-1 text-[11px] font-medium"
            style={{ background: "var(--border)", color: "var(--ink-2)" }}
          >
            Automatic
          </span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {["DuckDuckGo", "Bing", "Startpage", "Brave"].map((engine, i) => (
            <span key={engine} className="flex items-center gap-1.5">
              {i > 0 && (
                <span className="text-[11px] text-[var(--ink-3)]">→</span>
              )}
              <span className="rounded-md border border-[var(--line)] px-2 py-0.5 text-[11px] font-medium text-[var(--ink-2)]">
                {engine}
              </span>
            </span>
          ))}
        </div>
        <p className="mt-2.5 text-[12px] text-[var(--ink-3)]">
          The first engine that answers wins — no API key required.
        </p>
      </SettingsSection>

      <SettingsSection
        id="guidance"
        title="Guidance"
        subtitle="Replay the welcome tour and per-page intros."
      >
        <ReplayGuidance />
      </SettingsSection>

      <div id="tools">
        <OptionalToolsAndRuntimes />
      </div>
    </div>
  );
}

/** Re-arms tour + page intros and starts the spotlight tour from Today. */
function ReplayGuidance() {
  const navigate = useNavigate();
  const [replayed, setReplayed] = useState(false);
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">
          Product tour
        </p>
        <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
          Replay the three-step Today tour, and re-show page hints on your
          next visit to each page.
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          resetGuidance();
          setTourState("active");
          setReplayed(true);
          navigate("/");
        }}
        className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
        style={{ borderColor: "var(--border)", color: "var(--ink)" }}
      >
        {replayed ? "Tour restarted" : "Replay tour"}
      </button>
    </div>
  );
}

/** Sign-in — change workspace credentials. While the default login is still
 * active (must_change_password), this calls setup-credentials — no old
 * password required, username editable. Afterwards it calls change-password,
 * which needs the current password; the username stays fixed (the backend
 * has no rename path). */
function CredentialsForm({
  operator,
  onChanged,
}: {
  operator: Operator;
  onChanged: (op: Operator) => void;
}) {
  const { toast } = useConfirm();
  const firstRun = operator.must_change_password;
  const [username, setUsername] = useState(operator.username);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputStyle = {
    borderColor: "var(--border)",
    background: "var(--surface)",
    color: "var(--ink)",
  };
  const inputCls =
    "w-full rounded-md border px-3 py-2 text-[13px] transition-colors focus:outline-none focus:border-[var(--accent)]";
  const labelCls = "mb-1 block text-[12px] font-medium text-[var(--ink-2)]";

  const submit = async () => {
    setError(null);
    if (next.length < 8)
      return setError("New password needs at least 8 characters.");
    if (next !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      if (firstRun) {
        const op = await api.setupCredentials({
          username: username.trim() || undefined,
          new_password: next,
        });
        onChanged(op);
        toast("Sign-in updated");
      } else {
        await api.changePassword({
          old_password: current,
          new_password: next,
        });
        toast("Password updated");
      }
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update sign-in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="max-w-sm space-y-3"
    >
      {firstRun ? (
        <label className="block">
          <span className={labelCls}>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputCls}
            style={inputStyle}
            autoComplete="username"
          />
        </label>
      ) : (
        <label className="block">
          <span className={labelCls}>Current password</span>
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={inputCls}
            style={inputStyle}
            autoComplete="current-password"
          />
        </label>
      )}
      <label className="block">
        <span className={labelCls}>New password</span>
        <input
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className={inputCls}
          style={inputStyle}
          autoComplete="new-password"
        />
      </label>
      <label className="block">
        <span className={labelCls}>Confirm new password</span>
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={inputCls}
          style={inputStyle}
          autoComplete="new-password"
        />
      </label>
      {error && (
        <p role="alert" className="text-[12px]" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      <div>
        <button
          type="submit"
          disabled={
            busy || !next || !confirm || (!firstRun && !current)
          }
          className="rounded-md px-4 py-2 text-[12px] font-medium transition-opacity disabled:opacity-50"
          style={{ background: "var(--ink)", color: "var(--white)" }}
        >
          {busy ? "Saving…" : firstRun ? "Set sign-in" : "Update password"}
        </button>
      </div>
    </form>
  );
}

/** Appearance → "Show page hints" — clears the per-page dismissals and the
 * global don't-show-hints flag so intro cards come back on next visit. */
function HintReset() {
  const [restored, setRestored] = useState(false);
  return (
    <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4" style={{ borderColor: "var(--border-soft, var(--border))" }}>
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">Page hints</p>
        <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
          Intro cards at the top of Agents, Scheduler, Traces and other pages.
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          resetIntroFlags();
          setRestored(true);
        }}
        className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
        style={{ borderColor: "var(--border)", color: "var(--ink)" }}
      >
        {restored ? "Hints back on" : "Show page hints"}
      </button>
    </div>
  );
}

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function MiniAppFrame({ dark = false }: { dark?: boolean }) {
  // data-theme-preview scopes the real theme tokens to this subtree (see
  // index.css), so the swatch always mirrors the actual palette.
  return (
    <div
      className="flex h-full w-full"
      data-theme-preview={dark ? "dark" : "light"}
      style={{ background: "var(--ground)" }}
    >
      <div
        className="w-[28%]"
        style={{
          background: "var(--sunken)",
          borderRight: "1px solid var(--line)",
        }}
      />
      <div className="flex flex-1 flex-col gap-1 p-1.5">
        <div
          className="h-1.5 w-3/5 rounded-sm"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
          }}
        />
        <div
          className="h-1.5 w-4/5 rounded-sm"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
          }}
        />
        <div
          className="mt-auto h-1.5 w-2/5 rounded-sm"
          style={{ background: "var(--track)" }}
        />
      </div>
    </div>
  );
}

function ThemeSwatches({
  mode,
  onChange,
}: {
  mode: ThemeMode;
  onChange: (mode: ThemeMode) => void;
}) {
  return (
    <div
      className="grid grid-cols-3 gap-3"
      role="radiogroup"
      aria-label="Theme"
    >
      {THEME_OPTIONS.map((option) => {
        const selected = mode === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className="group text-left"
          >
            <span
              className="relative block h-20 overflow-hidden rounded-lg border-2 transition-colors"
              style={{
                borderColor: selected ? "var(--accent)" : "var(--border)",
              }}
            >
              {option.value === "system" ? (
                <>
                  <MiniAppFrame />
                  <span
                    className="absolute inset-0"
                    style={{
                      clipPath: "polygon(58% 0, 100% 0, 100% 100%, 38% 100%)",
                    }}
                  >
                    <MiniAppFrame dark />
                  </span>
                </>
              ) : (
                <MiniAppFrame dark={option.value === "dark"} />
              )}
            </span>
            <span className="mt-1.5 flex items-center gap-1.5 text-[12px] text-[var(--ink)]">
              <span
                className="flex h-3 w-3 items-center justify-center rounded-full border"
                style={{
                  borderColor: selected ? "var(--accent)" : "var(--ink-3)",
                }}
              >
                {selected && (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--accent)" }}
                  />
                )}
              </span>
              <span className={selected ? "font-semibold" : "font-medium"}>
                {option.label}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// --- Browser automation (W4) -----------------------------------------------

interface BrowserRuntime {
  status: string;
  binary?: string;
  managed?: boolean;
  managed_binary?: string | null;
  source?: "override" | "system" | "managed";
  version?: string;
  installable?: boolean;
  detail?: string;
  install_progress?: {
    phase: string;
    downloaded: number;
    total: number | null;
  } | null;
}

interface BrowserProfileRow {
  id: string;
  name: string;
  allowed_domains: string[];
  description: string | null;
}

function BrowserTab() {
  const { confirm } = useConfirm();
  const [runtime, setRuntime] = useState<BrowserRuntime | null>(null);
  const [binaryOverride, setBinaryOverride] = useState("");
  const [overrideSource, setOverrideSource] = useState<
    "env" | "persisted" | "none"
  >("none");
  const [resolvedBinary, setResolvedBinary] = useState<string | null>(null);
  const [detected, setDetected] = useState<{ name: string; path: string }[]>(
    [],
  );
  const [profiles, setProfiles] = useState<BrowserProfileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newDomains, setNewDomains] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [anySite, setAnySite] = useState(false);
  const [customPath, setCustomPath] = useState("");
  const [pickingCustom, setPickingCustom] = useState(false);
  const [pickingBuiltin, setPickingBuiltin] = useState(false);
  const [showLocation, setShowLocation] = useState(false);
  const [testingWindow, setTestingWindow] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [settings, profileList] = await Promise.all([
        api.getBrowserSettings(),
        api.listBrowserProfiles(),
      ]);
      setBinaryOverride(settings.binary_override);
      setOverrideSource(settings.override_source);
      setResolvedBinary(settings.resolved_binary);
      setDetected(settings.detected);
      if (
        settings.binary_override &&
        !settings.detected.some((d) => d.path === settings.binary_override)
      ) {
        setCustomPath(settings.binary_override);
      }
      setRuntime(settings.runtime);
      setProfiles(profileList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const applyOverride = async (path: string) => {
    setError(null);
    setNotice(null);
    try {
      const result = await api.updateBrowserSettings(path.trim());
      setBinaryOverride(result.binary_override);
      setOverrideSource(result.override_source);
      setResolvedBinary(result.resolved_binary);
      setDetected(result.detected);
      setRuntime(result.runtime);
      setNotice(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const managedBinary = runtime?.managed_binary ?? null;
  const engineValue = pickingCustom
    ? "custom"
    : pickingBuiltin
      ? "builtin"
      : !binaryOverride
        ? "auto"
        : managedBinary && binaryOverride === managedBinary
          ? "builtin"
          : detected.some((d) => d.path === binaryOverride)
            ? binaryOverride
            : "custom";

  const install = async () => {
    setInstalling(true);
    setError(null);
    const poller = setInterval(() => {
      void api
        .getBrowserSettings()
        .then((s) => setRuntime(s.runtime))
        .catch(() => {});
    }, 800);
    try {
      const result = await api.installBrowserRuntime();
      if (
        (result.status === "installed" || result.status === "ok") &&
        result.binary
      ) {
        setPickingBuiltin(false);
        await applyOverride(result.binary);
        setNotice("Browser installed — agents can now browse the web.");
      } else {
        setNotice(result.detail ?? `Status: ${result.status}`);
        await loadAll();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      clearInterval(poller);
      setInstalling(false);
    }
  };

  const removeRuntime = async () => {
    const ok = await confirm({
      title: "Remove built-in browser?",
      message:
        "Agents won't be able to browse until you install it again or pick your own browser.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) {
      return;
    }
    try {
      await api.removeBrowserRuntime();
      if (managedBinary && binaryOverride === managedBinary) {
        await applyOverride("");
      }
      setNotice("Built-in browser removed.");
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const createProfile = async () => {
    setError(null);
    try {
      const domains = anySite
        ? []
        : newDomains
            .split(",")
            .map((d) => d.trim())
            .filter(Boolean);
      await api.createBrowserProfile(
        newName.trim(),
        domains,
        newDesc.trim() || undefined,
      );
      setNewName("");
      setNewDomains("");
      setNewDesc("");
      setAnySite(false);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const openTestWindow = async () => {
    setTestingWindow(true);
    setError(null);
    try {
      const r = await api.openBrowserTestWindow();
      setNotice(
        `Test window opened — it closes by itself after ~${r.auto_close_seconds}s, or when you close it.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTestingWindow(false);
    }
  };

  const removeProfile = async (id: string) => {
    const ok = await confirm({
      title: "Forget this saved login?",
      message: "The agent will be logged out of these sites.",
      confirmLabel: "Forget",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteBrowserProfile(id);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (loading) {
    return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;
  }

  const status = runtime?.status ?? "runtime_unavailable";
  const available = status === "ok" || status === "installed";

  const selectEngine = (v: string) => {
    setPickingCustom(false);
    setPickingBuiltin(false);
    if (v === "custom") {
      setPickingCustom(true);
      setCustomPath(
        binaryOverride &&
          binaryOverride !== managedBinary &&
          !detected.some((d) => d.path === binaryOverride)
          ? binaryOverride
          : "",
      );
    } else if (v === "builtin" && !managedBinary) {
      setPickingBuiltin(true);
    } else {
      void applyOverride(
        v === "auto" ? "" : v === "builtin" ? (managedBinary ?? "") : v,
      );
    }
  };

  const engineRow = (value: string, title: string, sub: string) => (
    <label
      key={value}
      className={`flex cursor-pointer items-start gap-2.5 border-b py-2.5 last:border-0 ${
        overrideSource === "env" ? "cursor-not-allowed opacity-60" : ""
      }`}
      style={{ borderColor: "var(--border-soft)" }}
    >
      <input
        type="radio"
        name="browser-engine"
        value={value}
        checked={engineValue === value}
        disabled={overrideSource === "env"}
        onChange={() => selectEngine(value)}
        className="mt-0.5 h-4 w-4 shrink-0"
        style={{ accentColor: "var(--accent)" }}
      />
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-[var(--ink)]">
          {title}
        </span>
        <span className="block text-[11px] text-[var(--ink-3)] break-all">
          {sub}
        </span>
      </span>
    </label>
  );

  return (
    <div className="max-w-4xl space-y-8">
      {error && (
        <div
          className="rounded-lg border px-4 py-3 text-[12px]"
          style={{
            borderColor: "var(--danger)",
            background: "color-mix(in srgb, var(--danger) 10%, transparent)",
            color: "var(--danger)",
          }}
        >
          {error}
        </div>
      )}
      {notice && (
        <div
          className="rounded-lg border px-4 py-3 text-[12px]"
          style={{
            borderColor: "var(--border)",
            background: "var(--accent-bg)",
            color: "var(--ink)",
          }}
        >
          {notice}
        </div>
      )}

      {/* Agent browser */}
      <section id="agent-browser">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Agent browser
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Choose the browser agents use to open websites.
        </p>
        <div
          className="rounded-xl p-5 space-y-3"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] font-medium text-[var(--ink)]">
                {available
                  ? runtime?.managed
                    ? "Built-in browser"
                    : runtime?.source === "system"
                      ? "Your browser (auto-detected)"
                      : "Your own browser"
                  : "No browser set up"}
              </p>
              <p className="mt-0.5 text-[12px] text-[var(--ink-3)] break-all">
                {available
                  ? runtime?.managed
                    ? `CaberOS's own copy of Chrome ${runtime.version ?? ""} — kept separate from your personal browser.`.trim()
                    : runtime?.source === "system"
                      ? `${resolvedBinary} — found on this machine, nothing to install`
                      : resolvedBinary
                  : "Install a browser and your agents can open websites, fill forms, and read pages for you."}
              </p>
            </div>
            <span
              className="rounded-full px-3 py-1 text-[11px] font-medium shrink-0"
              style={
                available
                  ? {
                      background:
                        "color-mix(in srgb, var(--success) 15%, transparent)",
                      color: "var(--success)",
                    }
                  : {
                      background:
                        "color-mix(in srgb, var(--warning) 15%, transparent)",
                      color: "var(--warning)",
                    }
              }
            >
              {available ? "Ready" : "Not installed"}
            </span>
          </div>

          {/* Engine radios */}
          <div
            className="border-t pt-3"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="mb-1 text-[12px] font-medium text-[var(--ink)]">
              Browser engine
            </p>
            <div>
              {engineRow(
                "auto",
                "Automatic",
                "Use a browser already on this machine, otherwise the built-in one.",
              )}
              {detected.map((d) => engineRow(d.path, d.name, d.path))}
              {engineRow(
                "builtin",
                "CaberOS browser (built-in)",
                managedBinary
                  ? "Always use the built-in copy."
                  : "Not installed — downloads on select.",
              )}
              {engineRow(
                "custom",
                "Custom path",
                "Point to a browser CaberOS didn't detect.",
              )}
            </div>

            {engineValue === "builtin" && !managedBinary && (
              <div className="mt-2 space-y-2">
                <div className="flex items-center gap-2">
                  <button
                    onClick={install}
                    disabled={installing}
                    className="cursor-pointer rounded-md px-3 py-1.5 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
                    style={{
                      background: "var(--accent)",
                      color: "var(--white)",
                    }}
                  >
                    {installing
                      ? "Installing…"
                      : "Download & install (~160 MB)"}
                  </button>
                  {!installing && (
                    <p className="text-[11px] text-[var(--ink-3)]">
                      CaberOS's own private copy of Chrome — one-time download.
                    </p>
                  )}
                </div>
                {installing &&
                  (() => {
                    const p = runtime?.install_progress;
                    const mb = (n: number) => (n / 1048576).toFixed(0);
                    const phaseLabel =
                      p?.phase === "downloading"
                        ? p.total
                          ? `Downloading… ${mb(p.downloaded)} / ${mb(p.total)} MB`
                          : `Downloading… ${mb(p.downloaded)} MB`
                        : p?.phase === "extracting"
                          ? "Extracting…"
                          : p?.phase === "verifying"
                            ? "Verifying install…"
                            : "Preparing download…";
                    const pct =
                      p?.phase === "downloading" && p.total
                        ? Math.min(100, (p.downloaded / p.total) * 100)
                        : null;
                    return (
                      <div className="space-y-1.5">
                        <div
                          className="h-1.5 w-full overflow-hidden rounded-full"
                          style={{ background: "var(--accent-bg)" }}
                        >
                          {pct !== null ? (
                            <div
                              className="h-full rounded-full transition-[width] duration-300"
                              style={{
                                width: `${pct}%`,
                                background: "var(--accent)",
                              }}
                            />
                          ) : (
                            <div
                              className="pulse h-full w-1/3 rounded-full"
                              style={{ background: "var(--accent)" }}
                            />
                          )}
                        </div>
                        <p className="text-[11px] text-[var(--ink-3)]">
                          {phaseLabel} — keep this tab open.
                        </p>
                      </div>
                    );
                  })()}
              </div>
            )}
            {engineValue === "custom" && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="text"
                  value={customPath}
                  onChange={(e) => setCustomPath(e.target.value)}
                  disabled={overrideSource === "env"}
                  placeholder={CHROME_PATH_EXAMPLE}
                  className="flex-1 rounded-lg border px-3 py-2 font-mono text-[12px] transition-colors hover:border-[var(--ink-3)] disabled:opacity-60"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
                <button
                  onClick={() => {
                    setPickingCustom(false);
                    void applyOverride(customPath);
                  }}
                  disabled={overrideSource === "env" || !customPath.trim()}
                  className="flex cursor-pointer items-center gap-1 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: "var(--ink)", color: "var(--white)" }}
                >
                  <Save className="h-3.5 w-3.5" /> Save
                </button>
              </div>
            )}
            {overrideSource === "env" && (
              <p
                className="mt-2 rounded-md border px-3 py-2 text-[12px]"
                style={{
                  borderColor: "var(--warning)",
                  background:
                    "color-mix(in srgb, var(--warning) 10%, transparent)",
                  color: "var(--warning)",
                }}
              >
                Set by <code>AGENTOS_BROWSER_BINARY</code> in your environment
                or <code>.env</code> file — remove it there to change it here.
              </p>
            )}
          </div>

          {/* Action row */}
          <div
            className="flex flex-wrap items-center gap-2 border-t pt-3"
            style={{ borderColor: "var(--border)" }}
          >
            <button
              onClick={openTestWindow}
              disabled={testingWindow || !resolvedBinary}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-50"
              style={{ borderColor: "var(--border)" }}
            >
              <Play className="h-3 w-3" />
              {testingWindow ? "Opening…" : "Open a test window"}
            </button>
            <button
              onClick={() => setShowLocation((s) => !s)}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)" }}
            >
              <Search className="h-3 w-3" />
              {showLocation ? "Hide location" : "Show location"}
            </button>
            {managedBinary && (
              <button
                onClick={removeRuntime}
                className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition hover:opacity-80"
                style={{
                  borderColor:
                    "color-mix(in srgb, var(--danger) 40%, transparent)",
                  color: "var(--danger)",
                }}
              >
                <Trash2 className="h-3 w-3" />
                Remove built-in browser
              </button>
            )}
          </div>
          {showLocation && (
            <p
              className="rounded-lg px-3 py-2 font-mono text-[11px] text-[var(--ink-2)] break-all"
              style={{ background: "var(--sunken)" }}
            >
              {resolvedBinary ?? "No engine resolved yet"}
              {managedBinary && managedBinary !== resolvedBinary
                ? `\nbuilt-in: ${managedBinary}`
                : ""}
            </p>
          )}

          <p className="text-[11px] text-[var(--ink-3)]">
            Agents browse in their own private copy of Chrome — your personal
            browser, passwords, and logins are never touched. Works even if you
            only have Safari.
          </p>
        </div>
      </section>

      {/* Saved logins */}
      <section id="saved-logins">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Saved logins
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Keep agents signed in, only where you allow it.
        </p>
        <div
          className="rounded-xl p-5 space-y-4"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <p className="text-[12px] text-[var(--ink-3)]">
            Let an agent stay logged in to a website between runs. You sign in
            once yourself and the agent reuses it. Each login only works on the
            sites you list.
          </p>

          {profiles.length === 0 ? (
            <p
              className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-[12px]"
              style={{
                background:
                  "color-mix(in srgb, var(--success) 12%, transparent)",
                color: "var(--success)",
              }}
            >
              <Check className="h-3.5 w-3.5" />
              No saved logins. Agents start logged out on every run.
            </p>
          ) : (
            <div className="space-y-2">
              {profiles.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-lg border px-3 py-2"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-[var(--ink)]">
                      {p.name}
                    </p>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {p.allowed_domains.length > 0
                        ? `only: ${p.allowed_domains.join(", ")}`
                        : "any website"}
                      {p.description ? ` — ${p.description}` : ""}
                    </p>
                  </div>
                  <button
                    onClick={() => removeProfile(p.id)}
                    className="cursor-pointer rounded-md p-1.5 text-[var(--ink-3)] transition-colors hover:text-red-600"
                    title="Forget this login"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div
            className="space-y-3 border-t pt-4"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="text-[12px] font-medium text-[var(--ink)]">
              Add a saved login
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="login-name"
                  className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
                >
                  Name
                </label>
                <input
                  id="login-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. shopping"
                  className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
              </div>
              <div>
                <label
                  htmlFor="login-note"
                  className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
                >
                  Note (optional)
                </label>
                <input
                  id="login-note"
                  type="text"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="What this login is for"
                  className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
              </div>
            </div>
            <div>
              <label
                htmlFor="login-sites"
                className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
              >
                Allowed sites
              </label>
              <input
                id="login-sites"
                type="text"
                value={newDomains}
                onChange={(e) => setNewDomains(e.target.value)}
                disabled={anySite}
                placeholder="saucedemo.com, github.com"
                className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)] disabled:opacity-50"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                  color: "var(--ink)",
                }}
              />
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-[12px] text-[var(--ink-2)]">
              <input
                type="checkbox"
                checked={anySite}
                onChange={(e) => setAnySite(e.target.checked)}
                className="h-4 w-4"
                style={{ accentColor: "var(--accent)" }}
              />
              Allow on any site{" "}
              <span style={{ color: "var(--warning, #b45309)" }}>
                (not recommended)
              </span>
            </label>
            <button
              onClick={createProfile}
              disabled={!newName.trim() || (!anySite && !newDomains.trim())}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add login
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

interface ImportResult {
  status: string;
  mode: string;
  imported_files?: number;
  rows_added?: number;
  rows_skipped?: number;
  files_added?: number;
  tables_merged?: string[];
  secret_keys_match?: boolean;
  warnings?: string[];
  message: string;
}

interface PreviewTable {
  table: string;
  imported_count: number;
  target_count: number;
  new_in_merge: number;
}

interface PreviewResult {
  status: string;
  tables: PreviewTable[];
  agent_files: number;
  workspace_files: number;
  has_secret_key: boolean;
  secret_keys_match: boolean | null;
}

function MigrationTab() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const { confirm, toast } = useConfirm();

  const handleExport = async () => {
    setBusy(true);
    try {
      const resp = await fetch(`${api.baseURL}/api/data/export`, {
        credentials: "include",
        headers: api.authHeaders(),
      });
      if (!resp.ok) throw new Error("Export failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `caberos-backup-${Date.now()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Export downloaded");
    } catch {
      toast("Export failed");
    } finally {
      setBusy(false);
    }
  };

  // Single entry point: pick or drop a file -> auto-preview -> choose action
  const startPreview = async (file: File) => {
    setSelectedFile(file);
    setPreview(null);
    setResult(null);
    setBusy(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const resp = await fetch(`${api.baseURL}/api/data/preview`, {
        method: "POST",
        credentials: "include",
        headers: api.authHeaders(),
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        toast(`Preview failed: ${err.detail || "unknown error"}`);
        setSelectedFile(null);
      } else {
        setPreview(await resp.json());
      }
    } catch (err) {
      toast(`Preview failed: ${err}`);
      setSelectedFile(null);
    } finally {
      setBusy(false);
    }
  };

  const handlePickFile = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) void startPreview(file);
    };
    input.click();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      toast("Import expects a .zip archive from Export");
      return;
    }
    void startPreview(file);
  };

  const handleImport = (importMode: "replace" | "merge") => {
    if (!selectedFile) return;
    const doImport = async () => {
      const confirmed = await confirm({
        title: importMode === "replace" ? "Replace All Data?" : "Merge Data?",
        message:
          importMode === "replace"
            ? "This will WIPE all current data (agents, providers, MCP, channels, sessions, memory) and restore everything from the archive. This cannot be undone."
            : "This will add new data from the archive into the current instance. Existing data is kept. Encrypted credentials only work if both instances share the same secret key.",
        confirmLabel: importMode === "replace" ? "Wipe & Restore" : "Merge",
        cancelLabel: "Cancel",
        danger: importMode === "replace",
      });
      if (!confirmed) return;

      setBusy(true);
      setResult(null);
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("mode", importMode);
      try {
        const resp = await fetch(`${api.baseURL}/api/data/import`, {
          method: "POST",
          credentials: "include",
          headers: api.authHeaders(),
          body: formData,
        });
        if (!resp.ok) {
          const err = await resp.json();
          toast(`Import failed: ${err.detail || "unknown error"}`);
        } else {
          const res = (await resp.json()) as ImportResult;
          setResult(res);
          toast(
            importMode === "replace"
              ? "Data replaced — restart the server"
              : "Data merged — restart the server",
          );
        }
      } catch (err) {
        toast(`Import failed: ${err}`);
      } finally {
        setBusy(false);
      }
    };
    doImport();
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
  };

  const handleDeleteAll = async () => {
    const confirmed = await confirm({
      title: "Delete all CaberOS data?",
      message:
        "This permanently deletes agents, providers, MCP credentials, channels, sessions, memory, workspaces, attachments, and restore points. This cannot be undone.",
      confirmLabel: "Delete everything",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      await api.deleteAllData();
      resetGuidance();
      localStorage.removeItem("agentos_session_token");
      window.location.assign("/login");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete all data");
      setBusy(false);
    }
  };

  const step = !selectedFile ? 1 : result ? 3 : preview ? 3 : 2;
  const STEPS = [
    { n: 1, title: "Choose an archive", sub: "A .zip from Export" },
    { n: 2, title: "Review", sub: "See what's inside" },
    { n: 3, title: "Merge or replace", sub: "Merge keeps your data" },
  ];

  return (
    <div className="max-w-4xl space-y-8">
      {/* Export */}
      <section id="export">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Export</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Back up or move your workspace.
        </p>
        <div
          className="flex gap-8 rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="min-w-0 flex-1">
            <p className="text-[13px] text-[var(--ink-2)]">
              Save everything to one ZIP archive. Import it on another instance,
              for example web to desktop, to bring it all across.
            </p>
            <button
              onClick={handleExport}
              disabled={busy}
              className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: "var(--ink)", color: "var(--white)" }}
            >
              <Download className="h-3.5 w-3.5" />
              Export data
            </button>
          </div>
          <div
            className="w-56 shrink-0 border-l pl-5"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--ink-3)]">
              Included
            </p>
            <ul className="space-y-1.5">
              {[
                "Agents and versioned configs",
                "Providers and encrypted API keys",
                "MCP servers and channels",
                "Sessions, messages and memory",
                "Workspace files",
                "Secret key (credential decryption)",
              ].map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-1.5 text-[12px] text-[var(--ink-2)]"
                >
                  <Check className="h-3 w-3 shrink-0 text-[var(--accent)]" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Import — pick file -> preview -> merge/replace */}
      <section id="import">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Import</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Bring in an archive from another CaberOS.
        </p>
        <div
          className="rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          {/* Stepper */}
          <div className="mb-5 flex items-start">
            {STEPS.map((s, i) => (
              <div
                key={s.n}
                className={`flex items-start gap-2.5 ${i < STEPS.length - 1 ? "flex-1" : ""}`}
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                  style={{
                    background:
                      s.n <= step ? "var(--accent)" : "var(--border-soft)",
                    color: s.n <= step ? "var(--white)" : "var(--ink-3)",
                  }}
                >
                  {s.n < step ? <Check className="h-3 w-3" /> : s.n}
                </span>
                <span className="min-w-0">
                  <span
                    className="block text-[12px] font-semibold"
                    style={{
                      color: s.n <= step ? "var(--ink)" : "var(--ink-3)",
                    }}
                  >
                    {s.title}
                  </span>
                  <span className="block text-[11px] text-[var(--ink-3)]">
                    {s.sub}
                  </span>
                </span>
                {i < STEPS.length - 1 && (
                  <span
                    className="mx-4 mt-3 h-px flex-1"
                    style={{ background: "var(--border)" }}
                  />
                )}
              </div>
            ))}
          </div>

          {/* Step 1: Pick or drop file */}
          {!selectedFile && !result && (
            <button
              onClick={handlePickFile}
              onDragOver={(e) => {
                e.preventDefault();
                if (!busy) setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              disabled={busy}
              className="flex w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-10 text-center transition"
              style={{
                borderColor: dragActive
                  ? "var(--accent)"
                  : "color-mix(in srgb, var(--accent) 45%, var(--border))",
                background: dragActive ? "var(--accent-bg)" : "var(--surface)",
                cursor: busy ? "default" : "pointer",
              }}
            >
              <Upload
                className="mb-1 h-5 w-5"
                style={{ color: "var(--accent)" }}
              />
              <span className="text-[13px] font-semibold text-[var(--ink)]">
                {busy
                  ? "Analyzing archive…"
                  : "Choose a .zip archive to import"}
              </span>
              <span className="text-[12px] text-[var(--ink-3)]">
                or drop it here
              </span>
            </button>
          )}

          {/* Step 2/3: Preview + action buttons */}
          {selectedFile && !result && (
            <div className="space-y-4">
              {/* Selected file */}
              <div
                className="flex items-center justify-between rounded-lg border px-3 py-2"
                style={{ borderColor: "var(--border-soft)" }}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <HardDrive className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                  <span className="truncate text-[13px] font-semibold text-[var(--ink)]">
                    {selectedFile.name}
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--ink-3)]">
                    {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                </div>
                <button
                  onClick={handleReset}
                  disabled={busy}
                  className="flex shrink-0 items-center gap-1 text-[11px] text-[var(--ink-3)] transition hover:text-[var(--ink)]"
                  style={{ cursor: busy ? "default" : "pointer" }}
                >
                  <X className="h-3 w-3" />
                  Change file
                </button>
              </div>

              {/* Loading state */}
              {busy && !preview && (
                <div className="flex items-center gap-2 text-[12px] text-[var(--ink-3)]">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  Analyzing archive…
                </div>
              )}

              {/* Preview results */}
              {preview && (
                <div
                  className="overflow-hidden rounded-xl border"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  {/* Secret key indicator */}
                  <div
                    className="flex items-center gap-1.5 border-b px-4 py-2.5 text-[12px]"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    {preview.secret_keys_match === true ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
                        <span className="text-[var(--ink-2)]">
                          Secret keys match — credentials will decrypt
                        </span>
                      </>
                    ) : preview.secret_keys_match === false ? (
                      <>
                        <Info className="h-3.5 w-3.5 text-[var(--danger)]" />
                        <span className="text-[var(--danger)]">
                          Secret keys differ — credentials won't decrypt after
                          merge
                        </span>
                      </>
                    ) : (
                      <span className="text-[var(--ink-3)]">
                        No secret key in archive
                      </span>
                    )}
                  </div>

                  {/* Table breakdown */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr
                          className="border-b text-[11px] font-medium text-[var(--ink-3)]"
                          style={{ borderColor: "var(--border-soft)" }}
                        >
                          <th className="py-2 pl-4 pr-4 text-left font-medium">
                            Table
                          </th>
                          <th className="px-4 py-2 text-right font-medium">
                            In archive
                          </th>
                          <th className="px-4 py-2 text-right font-medium">
                            Current
                          </th>
                          <th className="py-2 pl-4 pr-4 text-right font-medium">
                            New (merge)
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.tables.map((t) => (
                          <tr
                            key={t.table}
                            className="border-b last:border-0"
                            style={{ borderColor: "var(--border-soft)" }}
                          >
                            <td className="py-2 pl-4 pr-4 font-mono text-[var(--ink)]">
                              {t.table}
                            </td>
                            <td className="px-4 py-2 text-right text-[var(--ink-2)]">
                              {t.imported_count}
                            </td>
                            <td className="px-4 py-2 text-right text-[var(--ink-2)]">
                              {t.target_count}
                            </td>
                            <td className="py-2 pl-4 pr-4 text-right">
                              <span
                                style={{
                                  color:
                                    t.new_in_merge > 0
                                      ? "var(--accent)"
                                      : "var(--ink-3)",
                                }}
                              >
                                {t.new_in_merge > 0
                                  ? `+${t.new_in_merge}`
                                  : "0"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* File counts */}
                  <div
                    className="flex gap-4 border-t px-4 py-2.5 text-[12px] text-[var(--ink-3)]"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <span>{preview.agent_files} agent files</span>
                    <span>{preview.workspace_files} workspace files</span>
                    {preview.has_secret_key && <span>includes secret.key</span>}
                  </div>
                </div>
              )}

              {/* Action buttons — only after preview loads */}
              {preview && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {/* Merge */}
                  <div
                    className="rounded-xl border p-4"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-[var(--ink)]">
                        Merge
                      </span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{
                          background: "var(--accent-bg)",
                          color: "var(--accent)",
                        }}
                      >
                        Recommended
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                      Keep existing data, add new items from the archive.
                    </p>
                    <button
                      onClick={() => handleImport("merge")}
                      disabled={busy}
                      className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
                      style={{
                        background: "var(--ink)",
                        color: "var(--white)",
                      }}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      Merge import
                    </button>
                  </div>

                  {/* Replace */}
                  <div
                    className="rounded-xl border p-4"
                    style={{
                      borderColor:
                        "color-mix(in srgb, var(--danger) 45%, transparent)",
                      background:
                        "color-mix(in srgb, var(--danger) 5%, transparent)",
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-[var(--ink)]">
                        Replace
                      </span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{
                          background:
                            "color-mix(in srgb, var(--danger) 14%, transparent)",
                          color: "var(--danger)",
                        }}
                      >
                        Destructive
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                      Wipe all current data, restore from archive.
                    </p>
                    <button
                      onClick={() => handleImport("replace")}
                      disabled={busy}
                      className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                      style={{
                        borderColor: "var(--danger)",
                        color: "var(--danger)",
                      }}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      Replace import
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Import result */}
          {result && (
            <div>
              <div
                className="rounded-xl border p-4"
                style={{
                  borderColor: result.warnings?.length
                    ? "color-mix(in srgb, var(--danger) 45%, transparent)"
                    : "var(--border-soft)",
                  background: result.warnings?.length
                    ? "color-mix(in srgb, var(--danger) 5%, transparent)"
                    : "var(--surface)",
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Check className="h-4 w-4 text-[var(--accent)]" />
                    <span className="text-[13px] font-semibold text-[var(--ink)]">
                      Import {result.mode === "replace" ? "Replace" : "Merge"}{" "}
                      Complete
                    </span>
                  </div>
                  <button
                    onClick={handleReset}
                    className="flex items-center gap-1 text-[11px] text-[var(--ink-3)] transition hover:text-[var(--ink)]"
                  >
                    <X className="h-3 w-3" />
                    Done
                  </button>
                </div>

                {/* Replace mode stats */}
                {result.mode === "replace" && result.imported_files != null && (
                  <div className="mt-2 text-[12px] text-[var(--ink-2)]">
                    {result.imported_files} files restored from archive
                  </div>
                )}

                {/* Merge mode stats */}
                {result.mode === "merge" && (
                  <div className="mt-2 space-y-1.5 text-[12px] text-[var(--ink-2)]">
                    <div className="flex gap-4">
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.rows_added ?? 0}
                        </strong>{" "}
                        rows added
                      </span>
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.rows_skipped ?? 0}
                        </strong>{" "}
                        rows skipped (already exist)
                      </span>
                      <span>
                        <strong className="text-[var(--ink)]">
                          {result.files_added ?? 0}
                        </strong>{" "}
                        files added
                      </span>
                    </div>

                    {result.tables_merged &&
                      result.tables_merged.length > 0 && (
                        <div className="mt-2">
                          <span className="text-[var(--ink-3)]">
                            Tables updated:
                          </span>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {result.tables_merged.map((t) => (
                              <span
                                key={t}
                                className="rounded-full px-2 py-0.5 text-[10px] font-mono"
                                style={{
                                  background: "var(--accent-bg)",
                                  color: "var(--accent)",
                                }}
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Secret key match indicator */}
                    {result.secret_keys_match != null && (
                      <div className="mt-2 flex items-center gap-1.5">
                        {result.secret_keys_match ? (
                          <>
                            <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
                            <span className="text-[var(--ink-3)]">
                              Secret keys match — credentials will decrypt
                              correctly
                            </span>
                          </>
                        ) : (
                          <>
                            <Info className="h-3.5 w-3.5 text-[var(--danger)]" />
                            <span className="text-[var(--danger)]">
                              Secret keys differ — re-enter credentials in the
                              target instance
                            </span>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Warnings */}
                {result.warnings && result.warnings.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {result.warnings.map((w, i) => (
                      <p key={i} className="text-[12px] text-[var(--danger)]">
                        ⚠ {w}
                      </p>
                    ))}
                  </div>
                )}

                <p className="mt-3 text-[11px] font-medium text-[var(--ink)]">
                  Restart the server for changes to take effect.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Danger zone */}
      <section id="danger-zone">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Danger zone
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Actions you can't take back.
        </p>
        <div
          className="flex items-center justify-between gap-6 rounded-xl p-5"
          style={{
            border: "1px solid var(--danger)",
            background: "var(--surface)",
          }}
        >
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-[var(--danger)]">
              Delete all data
            </p>
            <p className="mt-1 text-[12px] text-[var(--ink-2)]">
              Removes all local CaberOS data and returns to the first-run setup.
              Export first if you might need it again. This cannot be undone.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleDeleteAll()}
            disabled={busy}
            className="shrink-0 rounded-lg border px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
            style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
          >
            Delete all data…
          </button>
        </div>
      </section>
    </div>
  );
}

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

function ProvidersTab({
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

function ProviderTile({ name }: { name: string }) {
  return (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-[13px] font-semibold"
      style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
    >
      {name.charAt(0).toUpperCase()}
    </span>
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

/** Compact capability hint — " · 128K · thinking · vision" — used on both
 * catalog picker options and mapped rows. Only documented flags surface. */
function capabilitySuffix(m: {
  context_window_tokens?: number | null;
  supports_thinking?: boolean | null;
  supports_vision?: boolean | null;
}): string {
  const bits = [
    m.context_window_tokens
      ? `${Math.round(m.context_window_tokens / 1000)}K`
      : null,
    m.supports_thinking ? "thinking" : null,
    m.supports_vision ? "vision" : null,
  ].filter(Boolean);
  return bits.length ? ` · ${bits.join(" · ")}` : "";
}

/** Declared catalog-identity editor for alias providers. Local snapshot
 * read only — the operator picks the exact catalog model their deployment
 * name actually serves. */
function CatalogMappingEditor({
  provider,
  model,
  onDone,
}: {
  provider: Provider;
  model: ModelInfo;
  onDone: () => void;
}) {
  const [catalogProviders, setCatalogProviders] = useState<
    { id: string; name: string; models: number }[]
  >([]);
  const [catalogProviderId, setCatalogProviderId] = useState(
    model.catalog_provider_id || "",
  );
  const [catalogModels, setCatalogModels] = useState<
    {
      id: string;
      name: string;
      context_window_tokens: number | null;
      supports_thinking?: boolean | null;
      supports_vision?: boolean | null;
    }[]
  >([]);
  const [catalogModelId, setCatalogModelId] = useState(
    model.catalog_model_id || "",
  );
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const { toast } = useConfirm();

  useEffect(() => {
    let cancelled = false;
    setLoadingCatalog(true);
    api
      .listCatalogModels(provider.id, catalogProviderId || undefined)
      .then((r) => {
        if (cancelled) return;
        setCatalogProviders(r.providers);
        setCatalogModels(r.models);
        if (!catalogProviderId && r.catalog_provider_id)
          setCatalogProviderId(r.catalog_provider_id);
      })
      .catch((e) => {
        if (!cancelled) toast(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingCatalog(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id, catalogProviderId]);

  const filteredModels = catalogModels.filter((m) => {
    if (!filter.trim()) return true;
    const q = filter.trim().toLowerCase();
    return m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q);
  });

  const save = async () => {
    if (!catalogProviderId || !catalogModelId) return;
    setSaving(true);
    try {
      await api.setModelMetadata(provider.id, model.name, {
        catalog_provider_id: catalogProviderId,
        catalog_model_id: catalogModelId,
      });
      onDone();
    } catch (e) {
      toast(String(e));
      setSaving(false);
    }
  };

  const clear = async () => {
    setSaving(true);
    try {
      await api.setModelMetadata(provider.id, model.name, {
        clear_catalog_mapping: true,
      });
      onDone();
    } catch (e) {
      toast(String(e));
      setSaving(false);
    }
  };

  return (
    <div
      className="mt-1.5 rounded-lg border px-3 py-2.5"
      style={{ borderColor: "var(--border-soft)", background: "var(--ground)" }}
    >
      <p className="mb-2 text-[11px] text-[var(--ink-3)]">
        Which catalog model does <span className="font-mono">{model.name}</span>{" "}
        actually serve?
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={catalogProviderId}
          onChange={(v) => {
            setCatalogProviderId(v);
            setCatalogModelId("");
          }}
          options={catalogProviders.map((p) => ({
            value: p.id,
            label: `${p.name} (${p.models})`,
          }))}
          ariaLabel="Catalog provider"
          placeholder="Catalog provider"
          className="w-56 rounded-lg border border-[var(--border)] bg-surface px-2.5 py-1.5 text-[12px] text-[var(--ink)] outline-none"
          align="left"
          panelClassName="text-[12px]"
        />
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--ink-3)]" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter catalog models…"
            className="w-full rounded-lg border px-2.5 py-1.5 pl-7 text-[12px] text-[var(--ink)] outline-none"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface)",
            }}
          />
        </div>
        <Select
          value={catalogModelId}
          onChange={setCatalogModelId}
          options={filteredModels.map((m) => ({
            value: m.id,
            label: `${m.name}${capabilitySuffix(m)}`,
          }))}
          ariaLabel="Catalog model"
          placeholder={
            loadingCatalog
              ? "Loading…"
              : catalogModels.length === 0
                ? "No models in catalog"
                : filteredModels.length === 0
                  ? "No matches"
                  : "Choose catalog model"
          }
          className="w-72 rounded-lg border border-[var(--border)] bg-surface px-2.5 py-1.5 text-[12px] text-[var(--ink)] outline-none"
          align="left"
          panelClassName="text-[12px]"
        />
        <button
          onClick={save}
          disabled={!catalogProviderId || !catalogModelId || saving}
          className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-[12px] font-medium"
          style={{
            background: "var(--ink)",
            color: "var(--white)",
            opacity: catalogProviderId && catalogModelId && !saving ? 1 : 0.5,
          }}
        >
          <Check className="h-3 w-3" />
          {saving ? "Saving…" : "Save"}
        </button>
        {model.catalog_mapping_explicit && (
          <button
            onClick={clear}
            disabled={saving}
            className="rounded-lg border px-2.5 py-1.5 text-[11px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            Clear
          </button>
        )}
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
  const [agents, setAgents] = useState<Agent[]>([]);
  const [discovered, setDiscovered] = useState<Record<string, ModelInfo[]>>({});
  const [discovering, setDiscovering] = useState<Record<string, boolean>>({});
  const [customProviderId, setCustomProviderId] = useState("");
  const [customName, setCustomName] = useState("");
  const [savingCustom, setSavingCustom] = useState(false);
  const [chipPage, setChipPage] = useState<Record<string, number>>({});
  const [mappingKey, setMappingKey] = useState<string | null>(null);
  const [mappingOpen, setMappingOpen] = useState<Set<string>>(new Set());
  const { toast } = useConfirm();
  const navigate = useNavigate();
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    api
      .listAgents()
      .then((a) => {
        if (mounted.current) setAgents(a);
      })
      .catch(() => {});
  }, []);

  const loadModels = useCallback((providerId: string) => {
    api
      .listModels(providerId)
      .then((r) => {
        if (mounted.current)
          setDiscovered((prev) => ({ ...prev, [providerId]: r.models }));
      })
      .catch(() => {});
  }, []);

  // Cached offerings are a local read — this never hits the provider.
  useEffect(() => {
    setCustomProviderId((prev) =>
      providers.some((p) => p.id === prev) ? prev : providers[0]?.id || "",
    );
    for (const p of providers) loadModels(p.id);
  }, [providers, loadModels]);

  const handleDiscover = async (provider: Provider) => {
    setDiscovering((prev) => ({ ...prev, [provider.id]: true }));
    const done = () =>
      setDiscovering((prev) => ({ ...prev, [provider.id]: false }));
    try {
      // Explicit refresh — schedules backend discovery; the GET itself is
      // local so the first read returns current offerings immediately.
      await api.refreshProviderModels(provider.id).catch(() => null);
      let waited = 0;
      for (;;) {
        if (!mounted.current) return;
        const resp = await api.listModels(provider.id);
        if (!mounted.current) return;
        setDiscovered((prev) => ({ ...prev, [provider.id]: resp.models }));
        if (resp.refresh_in_progress !== true) break;
        waited += 1;
        if (waited >= 60) {
          toast("Refresh is still running; re-check later");
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) {
      if (mounted.current) toast(String(e));
    } finally {
      if (mounted.current) done();
    }
  };

  const discoverAll = () => {
    for (const p of providers) void handleDiscover(p);
  };

  const customProvider = providers.find((p) => p.id === customProviderId);

  const handleAddCustom = async () => {
    const name = customName.trim();
    if (!name || !customProvider) return;
    setSavingCustom(true);
    try {
      await api.addCustomModel(customProvider.id, name);
      setCustomName("");
      onChanged();
    } catch (e) {
      toast(String(e));
    } finally {
      if (mounted.current) setSavingCustom(false);
    }
  };

  const handleRemoveCustom = async (provider: Provider, modelName: string) => {
    try {
      await api.removeCustomModel(provider.id, modelName);
      onChanged();
    } catch (e) {
      toast(String(e));
    }
  };

  if (loading)
    return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;
  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Cpu className="h-8 w-8 text-[var(--ink-3)]" />
        <p className="mt-3 text-[14px] text-[var(--ink-2)]">
          No providers configured
        </p>
        <p className="mt-1 text-[12px] text-[var(--ink-3)]">
          Add a provider first to manage models.
        </p>
      </div>
    );
  }

  // Group agents by (provider, model) for the In use table; agents with no
  // model get their own actionable rows.
  const providerName = (id: string | null) =>
    providers.find((p) => p.id === id)?.name ?? "—";
  const inUse = new Map<
    string,
    { model: string; provider: string; usedBy: string[] }
  >();
  const unsetAgents: Agent[] = [];
  for (const a of agents) {
    if (!a.model || !a.provider_id) {
      unsetAgents.push(a);
      continue;
    }
    const key = `${a.provider_id}::${a.model}`;
    const row = inUse.get(key) ?? {
      model: a.model,
      provider: providerName(a.provider_id),
      usedBy: [],
    };
    row.usedBy.push(a.name);
    inUse.set(key, row);
  }
  const inUseRows = [...inUse.values()].sort((a, b) =>
    a.model.localeCompare(b.model),
  );

  return (
    <div className="max-w-4xl space-y-8">
      {/* In use */}
      <section id="in-use">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">In use</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Models your agents are set to.
        </p>
        <div
          className="overflow-hidden rounded-xl border"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <table className="w-full text-left">
            <thead>
              <tr
                className="border-b text-[12px] font-medium text-[var(--ink-3)]"
                style={{ borderColor: "var(--border-soft)" }}
              >
                <th className="w-[30%] px-5 py-2.5 font-medium">Model</th>
                <th className="w-[20%] px-5 py-2.5 font-medium">Provider</th>
                <th className="px-5 py-2.5 font-medium">Used by</th>
              </tr>
            </thead>
            <tbody>
              {inUseRows.map((row) => (
                <tr
                  key={`${row.provider}:${row.model}`}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[13px] font-medium text-[var(--ink)]">
                    {row.model}
                  </td>
                  <td className="px-5 py-3 text-[13px] text-[var(--ink)]">
                    {row.provider}
                  </td>
                  <td className="px-5 py-3 text-[12px] text-[var(--ink-2)]">
                    {row.usedBy.join(", ")}
                  </td>
                </tr>
              ))}
              {unsetAgents.map((a) => (
                <tr
                  key={a.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  <td
                    className="whitespace-nowrap px-5 py-3 font-mono text-[13px] font-medium"
                    style={{ color: "var(--warning, #b45309)" }}
                  >
                    No model set
                  </td>
                  <td className="px-5 py-3" />
                  <td className="px-5 py-3 text-[12px] text-[var(--ink-2)]">
                    {a.name} ·{" "}
                    <button
                      onClick={() => navigate("/agents")}
                      className="font-medium underline-offset-2 hover:underline"
                      style={{ color: "var(--accent)" }}
                    >
                      Choose a model
                    </button>
                  </td>
                </tr>
              ))}
              {inUseRows.length === 0 && unsetAgents.length === 0 && (
                <tr>
                  <td
                    colSpan={3}
                    className="px-5 py-6 text-center text-[12px] text-[var(--ink-3)]"
                  >
                    No agents yet — create one to see its model here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Discover models */}
      <section id="discover">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[14px] font-semibold text-[var(--ink)]">
              Discover models
            </h2>
            <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
              Fetch what each provider offers, then pick from the list when you
              set up an agent.
            </p>
          </div>
          <button
            onClick={discoverAll}
            disabled={providers.every((p) => discovering[p.id])}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
            style={{ borderColor: "var(--border)" }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Discover all
          </button>
        </div>
        <div className="space-y-2.5">
          {providers.map((provider) => {
            const all = discovered[provider.id] || [];
            const models = all.filter((m) => m.availability === "available");
            const errCount = all.filter((m) => m.discovery_error).length;
            const error =
              models.length === 0 && errCount > 0
                ? all.find((m) => m.discovery_error)?.discovery_error
                : null;
            const isDiscovering = discovering[provider.id];
            return (
              <div
                key={provider.id}
                className="rounded-xl border px-4 py-3.5"
                style={{
                  borderColor: "var(--border-soft)",
                  background: "var(--surface)",
                }}
              >
                <div className="flex items-center gap-3.5">
                  <ProviderTile name={provider.name} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-semibold text-[var(--ink)]">
                      {provider.name}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">
                      {isDiscovering ? (
                        "Fetching models…"
                      ) : error ? (
                        <span style={{ color: "var(--danger)" }}>
                          Discovery failed: {error}
                        </span>
                      ) : models.length > 0 ? (
                        <>
                          {models.length} models fetched · prefix{" "}
                          <span className="font-mono">{provider.type}/</span>
                          {errCount > 0 && ` · ${errCount} unconfirmed`}
                        </>
                      ) : (
                        <>
                          No models fetched yet · prefix{" "}
                          <span className="font-mono">{provider.type}/</span>
                        </>
                      )}
                    </p>
                  </div>
                  <button
                    onClick={() => handleDiscover(provider)}
                    disabled={isDiscovering}
                    className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${isDiscovering ? "animate-spin" : ""}`}
                    />
                    Discover
                  </button>
                </div>
                {models.length > 0 && (
                  <div
                    className="mt-3 border-t pt-3"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <div className="flex flex-wrap gap-1.5">
                      {models
                        .slice(
                          (chipPage[provider.id] || 0) * 24,
                          ((chipPage[provider.id] || 0) + 1) * 24,
                        )
                        .map((m) => (
                          <span
                            key={m.id}
                            className="rounded-full px-2.5 py-1 font-mono text-[11px]"
                            style={{
                              background: "var(--border)",
                              color: "var(--ink-2)",
                            }}
                            title={m.display_name || m.name}
                          >
                            {m.name}
                          </span>
                        ))}
                    </div>
                    {models.length > 24 && (
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <button
                          onClick={() =>
                            setChipPage((prev) => ({
                              ...prev,
                              [provider.id]: Math.max(
                                0,
                                (prev[provider.id] || 0) - 1,
                              ),
                            }))
                          }
                          disabled={(chipPage[provider.id] || 0) === 0}
                          aria-label="Previous page"
                          className="flex h-6 w-6 items-center justify-center rounded border text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-40"
                          style={{ borderColor: "var(--border)" }}
                        >
                          ‹
                        </button>
                        <span className="text-[11px] text-[var(--ink-3)]">
                          {(chipPage[provider.id] || 0) + 1}/
                          {Math.ceil(models.length / 24)}
                        </span>
                        <button
                          onClick={() =>
                            setChipPage((prev) => ({
                              ...prev,
                              [provider.id]: Math.min(
                                Math.ceil(models.length / 24) - 1,
                                (prev[provider.id] || 0) + 1,
                              ),
                            }))
                          }
                          disabled={
                            (chipPage[provider.id] || 0) >=
                            Math.ceil(models.length / 24) - 1
                          }
                          aria-label="Next page"
                          className="flex h-6 w-6 items-center justify-center rounded border text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-40"
                          style={{ borderColor: "var(--border)" }}
                        >
                          ›
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {(() => {
                  // Alias providers (azure deployments, bedrock profiles) carry
                  // operator-chosen names — catalog facts need a declared
                  // mapping. Also keep explicitly-mapped rows editable.
                  const unmapped = all.filter(
                    (m) =>
                      m.context_window_tokens == null ||
                      m.catalog_mapping_explicit,
                  );
                  if (unmapped.length === 0) return null;
                  const expanded = mappingOpen.has(provider.id);
                  return (
                    <div
                      className="mt-3 border-t pt-2.5"
                      style={{ borderColor: "var(--border-soft)" }}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setMappingOpen((prev) => {
                            const next = new Set(prev);
                            if (next.has(provider.id)) next.delete(provider.id);
                            else next.add(provider.id);
                            return next;
                          })
                        }
                        className="flex w-full items-center gap-2 text-left"
                      >
                        {expanded ? (
                          <ChevronDown className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
                        ) : (
                          <ChevronRight className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
                        )}
                        <span className="text-[11px] font-medium text-[var(--ink-2)]">
                          Catalog mappings
                        </span>
                        <span className="rounded-full bg-sunken px-1.5 py-px text-[9px] font-medium text-ink-muted">
                          ×{unmapped.length}
                        </span>
                        <span className="truncate text-[10px] text-[var(--ink-3)]">
                          map a name to resolve context and pricing
                        </span>
                      </button>
                      {expanded && (
                        <>
                          <p className="mb-2 mt-2 text-[11px] text-[var(--ink-3)]">
                            Models without catalog metadata — map a name to its
                            catalog entry to resolve context limits and
                            pricing.
                          </p>
                          <div className="space-y-1">
                        {unmapped.map((m) => {
                          const key = `${provider.id}::${m.id}`;
                          const open = mappingKey === key;
                          return (
                            <div key={key}>
                              <div className="flex items-center gap-2.5">
                                <span className="font-mono text-[12px] text-[var(--ink)]">
                                  {m.name}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--ink-3)]">
                                  {m.catalog_mapping_explicit
                                    ? `declared → ${m.catalog_provider_id}/${m.catalog_model_id}${capabilitySuffix(m)}`
                                    : "unknown metadata"}
                                </span>
                                <button
                                  onClick={() =>
                                    setMappingKey(open ? null : key)
                                  }
                                  className="flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                                  style={{ borderColor: "var(--border)" }}
                                >
                                  {open ? (
                                    <X className="h-3 w-3" />
                                  ) : (
                                    <Pencil className="h-3 w-3" />
                                  )}
                                  {open
                                    ? "Close"
                                    : m.catalog_mapping_explicit
                                      ? "Edit mapping"
                                      : "Map"}
                                </button>
                              </div>
                              {open && (
                                <CatalogMappingEditor
                                  provider={provider}
                                  model={m}
                                  onDone={() => {
                                    setMappingKey(null);
                                    loadModels(provider.id);
                                  }}
                                />
                              )}
                            </div>
                          );
                        })}
                          </div>
                        </>
                      )}
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      </section>

      {/* Add a custom model */}
      <section id="custom">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Add a custom model
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          For a model that doesn't show up in the list.
        </p>
        <div
          className="rounded-xl border p-5"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="flex items-end gap-3">
            <div className="w-52">
              <label
                htmlFor="custom-model-provider"
                className="mb-1 block text-[12px] font-medium text-[var(--ink-3)]"
              >
                Provider
              </label>
              <Select
                value={customProviderId}
                onChange={setCustomProviderId}
                options={providers.map((p) => ({ value: p.id, label: p.name }))}
                ariaLabel="Provider"
                className="w-full rounded-lg border border-[var(--border)] bg-surface px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                align="left" panelClassName="text-[13px]"
              />
            </div>
            <div className="min-w-0 w-56">
              <label
                htmlFor="custom-model-name"
                className="mb-1 block text-[12px] font-medium text-[var(--ink-3)]"
              >
                Model name
              </label>
              <input
                id="custom-model-name"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddCustom()}
                placeholder="model-name"
                className="w-full rounded-lg border px-3 py-2 font-mono text-[12px] text-[var(--ink)] outline-none"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                }}
              />
            </div>
            <button
              onClick={handleAddCustom}
              disabled={!customName.trim() || !customProvider || savingCustom}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12px] font-medium"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
                opacity:
                  customName.trim() && customProvider && !savingCustom
                    ? 1
                    : 0.5,
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add model
            </button>
          </div>
          <p className="mt-3 text-[11px] text-[var(--ink-3)]">
            The provider prefix is added for you, so{" "}
            <span className="font-mono">model-name</span> is saved as{" "}
            <span className="font-mono">
              {customProvider?.type ?? "provider"}/model-name
            </span>
            .
          </p>
          {customProvider &&
            (customProvider.custom_models || []).length > 0 && (
              <div
                className="mt-4 flex flex-wrap gap-1.5 border-t pt-4"
                style={{ borderColor: "var(--border-soft)" }}
              >
                {(customProvider.custom_models || []).map((m) => (
                  <span
                    key={m}
                    className="flex items-center gap-1 rounded-full px-2.5 py-1 font-mono text-[11px]"
                    style={{
                      background: "var(--accent-bg)",
                      color: "var(--accent)",
                    }}
                    title={`${customProvider.type}/${m}`}
                  >
                    {m}
                    <button
                      onClick={() => handleRemoveCustom(customProvider, m)}
                      aria-label={`Remove ${m}`}
                      className="flex items-center"
                      style={{ border: "none", background: "none", padding: 0 }}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
        </div>
      </section>
    </div>
  );
}

function AboutTab() {
  const [version, setVersion] = useState<string>("...");
  const [copied, setCopied] = useState(false);
  const updater = useUpdater();
  const { toast } = useConfirm();

  useEffect(() => {
    // In desktop mode, read from Tauri. In web mode, fetch from the backend.
    const isTauri =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
    if (isTauri) {
      // Tauri v2 — read the app version from the package info
      import("@tauri-apps/api/app")
        .then((mod) => mod.getVersion())
        .then(setVersion)
        .catch(() => {
          // Fallback to backend endpoint
          fetch(`${import.meta.env.VITE_API_BASE || ""}/api/version`)
            .then((r) => r.json())
            .then((data) => setVersion(data.version))
            .catch(() => setVersion("unknown"));
        });
    } else {
      fetch(`${import.meta.env.VITE_API_BASE || ""}/api/version`)
        .then((r) => r.json())
        .then((data) => setVersion(data.version))
        .catch(() => setVersion("unknown"));
    }
  }, []);

  const handleCheckUpdates = useCallback(async () => {
    await refreshUpdates().catch(() => {});
  }, []);

  const handleDownload = useCallback(async () => {
    await downloadAndInstallUpdate().catch(() => {});
  }, []);

  const handleRestart = useCallback(async () => {
    await restartApp().catch(() => {});
  }, []);

  const copyDiagnostics = async () => {
    const isTauri =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
    const lines = [
      `CaberOS ${version}`,
      `Shell: ${isTauri ? "Tauri desktop" : "web"}`,
      `User agent: ${navigator.userAgent}`,
      `API: ${api.baseURL || window.location.origin}`,
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Copy failed — clipboard permission denied");
    }
  };

  const statusLine = (() => {
    switch (updater.status) {
      case "idle":
        return "Check for updates to see if you're current";
      case "checking":
        return "Checking…";
      case "up-to-date":
        return isDesktopMode()
          ? "You're up to date"
          : "Update checks run in the desktop app";
      case "available":
        return `v${updater.info?.latestVersion} is available`;
      case "downloading":
        return updater.progress.downloaded && updater.progress.total
          ? `Downloading… ${Math.round((updater.progress.downloaded / updater.progress.total) * 100)}%`
          : "Downloading…";
      case "installing":
        return "Installing update…";
      case "ready":
        return "Update ready — restart to apply";
      case "error":
        return updater.error || "Update check failed";
    }
  })();

  const LINKS = [
    {
      label: "GitHub repository",
      sub: "Source and releases",
      href: "https://github.com/cabernect/caberos",
    },
    {
      label: "Report an issue",
      sub: "Include your diagnostics",
      href: "https://github.com/cabernect/caberos/issues",
    },
    {
      label: "Security",
      sub: "How to report a vulnerability",
      href: "https://github.com/cabernect/caberos/security",
    },
  ];

  return (
    <div className="max-w-4xl space-y-8">
      {/* CaberOS */}
      <section id="caberos">
        <div
          className="flex items-center gap-4 rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <span
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl"
            style={{ background: "var(--accent-bg)" }}
          >
            <LogoMark className="h-8 w-8" color="var(--brand)" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">
              CaberOS
            </h2>
            <p className="text-[12px] text-[var(--ink-3)]">
              Local-first AI Agent Operating System
            </p>
            <p className="mt-1 flex items-center gap-1.5 text-[12px]">
              <span className="font-mono font-medium text-[var(--ink)]">
                v{version}
              </span>
              <span
                className="text-[var(--ink-3)]"
                style={{
                  color:
                    updater.status === "up-to-date" ||
                    updater.status === "available" ||
                    updater.status === "ready"
                      ? "var(--accent)"
                      : updater.status === "error"
                        ? "var(--danger)"
                        : undefined,
                }}
              >
                · {statusLine}
              </span>
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {updater.status === "idle" && (
              <button
                onClick={handleCheckUpdates}
                className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                style={{ borderColor: "var(--border)" }}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Check for updates
              </button>
            )}
            {updater.status === "available" && (
              <>
                <button
                  onClick={() => resetUpdater()}
                  className="rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                  style={{ borderColor: "var(--border)" }}
                >
                  Later
                </button>
                <button
                  onClick={handleDownload}
                  className="rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90"
                  style={{ background: "var(--ink)", color: "var(--white)" }}
                >
                  Download update
                </button>
              </>
            )}
            {updater.status === "ready" && (
              <button
                onClick={handleRestart}
                className="rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90"
                style={{ background: "var(--ink)", color: "var(--white)" }}
              >
                Restart now
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Built with */}
      <section id="built-with">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Built with
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          What's running under the hood.
        </p>
        <div
          className="rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="grid grid-cols-2 gap-x-6 gap-y-4">
            {[
              ["Backend", "Python 3.12, FastAPI, SQLAlchemy, LiteLLM"],
              ["Frontend", "React 19, Vite, Tailwind CSS 4, Tauri 2"],
              ["Database", "SQLite (WAL) default, PostgreSQL optional"],
              ["Sandbox", "Seatbelt · bubblewrap · Docker · MXC (Windows)"],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-[12px] text-[var(--ink-3)]">{label}</p>
                <p className="mt-0.5 text-[13px] font-medium text-[var(--ink)]">
                  {value}
                </p>
              </div>
            ))}
          </div>
          <div
            className="mt-5 border-t pt-4"
            style={{ borderColor: "var(--border-soft)" }}
          >
            <button
              onClick={copyDiagnostics}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)" }}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
              ) : (
                <ClipboardCopy className="h-3.5 w-3.5" />
              )}
              {copied ? "Copied" : "Copy diagnostics"}
            </button>
            <p className="mt-1.5 text-[11px] text-[var(--ink-3)]">
              Version, system and shell details for bug reports.
            </p>
          </div>
        </div>
      </section>

      {/* Links */}
      <section id="links">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Links</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Help and source.
        </p>
        <div
          className="overflow-hidden rounded-xl border"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          {LINKS.map((l) => (
            <a
              key={l.label}
              href={l.href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={openExternal}
              className="flex items-center justify-between border-b px-5 py-3 transition last:border-0 hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border-soft)" }}
            >
              <span className="flex items-baseline gap-3">
                <span className="text-[13px] font-medium text-[var(--ink)]">
                  {l.label}
                </span>
                <span className="text-[12px] text-[var(--ink-3)]">{l.sub}</span>
              </span>
              <span className="text-[12px] font-medium text-[var(--accent)]">
                Open
              </span>
            </a>
          ))}
        </div>
      </section>

      {/* License */}
      <section id="license">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">License</h2>
        <div
          className="mt-3 rounded-xl p-5 text-[13px] text-[var(--ink-2)]"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <p>MIT License. Copyright (c) 2026 HoangPH25.</p>
          <p className="mt-1 text-[var(--ink-3)]">
            Fonts: Geist and Geist Mono (SIL Open Font License 1.1).
          </p>
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">
        {label}
      </label>
      {children}
    </div>
  );
}
