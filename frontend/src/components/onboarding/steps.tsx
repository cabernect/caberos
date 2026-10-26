import { useEffect, useState } from "react";
import {
  AppWindow,
  Check,
  Cloud,
  Cpu,
  FileText,
  GitBranch,
  Globe,
  LoaderCircle,
  Lock,
  Pencil,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  Agent,
  CapabilityInfo,
  ModelInfo,
  Operator,
  Provider,
  RuntimeDependency,
  SandboxHealth,
} from "@/lib/types";
import { Select } from "@/components/ui/select";
import {
  BackButton,
  CalloutBox,
  Field,
  IconTile,
  PrimaryButton,
  StepSub,
  StepTitle,
  StrengthMeter,
  inputStyle,
} from "./parts";

/** Step components for the onboarding flow, per
 * docs/plans/v0.2/fe_example/Onboarding ·*. Each renders its content; the
 * orchestrator (Onboarding.tsx) owns navigation, persistence and skip. */

/* ------------------------------------------------------------------ */
/* Welcome — centered stage                                             */
/* ------------------------------------------------------------------ */

const WELCOME_POINTS = [
  {
    icon: Check,
    title: "You approve what matters",
    sub: "Agents ask before doing anything that counts.",
  },
  {
    icon: Lock,
    title: "Your data stays with you",
    sub: "Agents, memory and files live on this computer.",
  },
  {
    icon: GitBranch,
    title: "You can see what happened",
    sub: "Every action is recorded for you to open.",
  },
];

export function StepWelcome({
  onStart,
  onImport,
}: {
  onStart: () => void;
  onImport: () => void;
}) {
  return (
    <div className="flex flex-col items-center text-center">
      <img src="/_logo-mark.svg" alt="CaberOS" className="h-16 w-16" />
      <h1 className="mt-6 text-[34px] font-semibold tracking-tight text-[var(--ink)]">
        Welcome to CaberOS
      </h1>
      <p className="mt-2 max-w-md text-[14px] leading-6 text-[var(--ink-2)]">
        Personal AI agents that run on your machine, ask before they act, and keep
        a record of everything.
      </p>
      <div className="mt-9 w-full max-w-[400px] space-y-4 text-left">
        {WELCOME_POINTS.map((p) => (
          <div key={p.title} className="flex items-start gap-3.5">
            <IconTile icon={p.icon} />
            <div>
              <p className="text-[14px] font-semibold text-[var(--ink)]">
                {p.title}
              </p>
              <p className="mt-0.5 text-[12.5px] text-[var(--ink-2)]">{p.sub}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-9">
        <PrimaryButton onClick={onStart}>Get started</PrimaryButton>
      </div>
      <p className="mt-5 text-[12.5px] text-[var(--ink-3)]">
        Moving from another machine?{" "}
        <button
          type="button"
          onClick={onImport}
          className="font-medium underline"
          style={{ color: "var(--accent)", background: "none", border: "none", cursor: "pointer" }}
        >
          Import your data
        </button>
      </p>
      <p className="mt-16 text-[11.5px] text-[var(--ink-3)]">
        v{__APP_VERSION__} · Everything runs on this machine
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Protect your workspace — replace default credentials                  */
/* ------------------------------------------------------------------ */

function passwordScore(pw: string): { score: number; hint: string } {
  if (!pw) return { score: 0, hint: "Use at least 12 characters." };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[0-9]/.test(pw) && /[a-zA-Z]/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  const label =
    pw.length < 8
      ? "Too short — use at least 8 characters."
      : pw.length < 12
        ? "Okay. 12+ characters is stronger."
        : score >= 3
          ? "Strong. Keep it somewhere safe."
          : "Good. Adding symbols makes it stronger.";
  return { score: Math.min(score, 4), hint: label };
}

export function StepPassword({
  operator,
  onDone,
  onBack,
  onSkip,
  busy,
  setBusy,
}: {
  operator: Operator | null;
  onDone: (op: Operator) => void;
  onBack: () => void;
  onSkip: () => void;
  busy: boolean;
  setBusy: (b: boolean) => void;
}) {
  const [name, setName] = useState(operator?.username ?? "");
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const { score, hint } = passwordScore(pw);

  const submit = async () => {
    if (pw.length < 8) return setError("Use at least 8 characters.");
    if (pw !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    setError("");
    try {
      const op = await api.setupCredentials({
        username: name.trim() || undefined,
        new_password: pw,
      });
      onDone(op);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not set credentials.");
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
    >
      <StepTitle>Protect your workspace</StepTitle>
      <StepSub>
        CaberOS starts with a default login. Choose your own before you do
        anything else.
      </StepSub>
      <div className="mt-8 space-y-5">
        <Field label="Your name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={inputStyle}
            autoFocus
          />
        </Field>
        <Field label="New password">
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            style={inputStyle}
          />
          <StrengthMeter score={score} hint={hint} />
        </Field>
        <Field label="Confirm password">
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            style={inputStyle}
          />
        </Field>
        <CalloutBox icon={Lock}>
          This replaces the default login. Your password is kept only on this
          machine. Keep it somewhere safe.
        </CalloutBox>
        {error && (
          <p role="alert" className="text-[12.5px] text-[var(--danger)]">
            {error}
          </p>
        )}
      </div>
      <div className="mt-14 flex items-center justify-between">
        <BackButton onClick={onBack} />
        <div className="flex items-center gap-5">
          <button
            type="button"
            onClick={onSkip}
            className="cursor-pointer text-[12.5px] text-[var(--ink-3)] underline"
            style={{ background: "none", border: "none" }}
          >
            Skip for now — keep the default login
          </button>
          <PrimaryButton type="submit" disabled={busy || !pw || !confirm}>
            {busy ? "Setting…" : "Continue"}
          </PrimaryButton>
        </div>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ */
/* Get your machine ready — runtime readiness                                */
/* ------------------------------------------------------------------ */

interface RuntimeRowState {
  status: "ready" | "installing" | "failed" | "optional";
  progress?: { downloaded: number; total: number | null } | null;
  error?: string;
}

export function StepRuntime({
  onDone,
  onBack,
}: {
  onDone: () => void;
  onBack: () => void;
}) {
  const [browser, setBrowser] = useState<RuntimeRowState>({ status: "optional" });
  const [sandbox, setSandbox] = useState<SandboxHealth | null | undefined>(
    undefined,
  );
  const [deps, setDeps] = useState<RuntimeDependency[] | null>(null);
  const [loading, setLoading] = useState(true);

  const loadBrowser = async () => {
    try {
      const info = await api.getBrowserSettings();
      const r = info.runtime;
      if (r.status === "ready" || r.status === "ok" || r.binary) {
        setBrowser({ status: "ready" });
      } else if (r.install_progress) {
        setBrowser({ status: "installing", progress: r.install_progress });
      } else {
        setBrowser({ status: "optional" });
      }
    } catch {
      setBrowser({ status: "optional" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadBrowser();
    api
      .getHealth()
      .then((h) => setSandbox(h.sandbox ?? null))
      .catch(() => setSandbox(null));
    // chromium is covered by the Browser row's own runtime check.
    api
      .getDependencies()
      .then((r) => setDeps(r.dependencies.filter((d) => d.id !== "chromium")))
      .catch(() => setDeps([]));
  }, []);

  // Poll while a download is in flight.
  useEffect(() => {
    if (browser.status !== "installing") return;
    const t = setInterval(() => void loadBrowser(), 1200);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browser.status]);

  const install = async () => {
    setBrowser({ status: "installing", progress: { downloaded: 0, total: null } });
    try {
      await api.installBrowserRuntime();
      await loadBrowser();
    } catch (e) {
      setBrowser({
        status: "failed",
        error: e instanceof Error ? e.message : "Download failed.",
      });
    }
  };

  const pct =
    browser.progress?.total && browser.progress.total > 0
      ? Math.round((browser.progress.downloaded / browser.progress.total) * 100)
      : null;

  return (
    <div>
      <StepTitle>Getting your machine ready</StepTitle>
      <StepSub>
        CaberOS needs a few things to run agents safely. Most are already here.
      </StepSub>
      <div className="mt-8 space-y-3">
        <RuntimeRow
          icon={Cpu}
          title="CaberOS engine"
          desc="Runs your agents on this machine."
          right={<ReadyBadge />}
        />
        <RuntimeRow
          icon={Globe}
          title="Browser for agents"
          desc="A private copy of Chrome, kept separate from yours, so agents can browse safely."
          right={
            loading ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--ink-3)]" />
            ) : browser.status === "ready" ? (
              <ReadyBadge />
            ) : browser.status === "failed" ? (
              <span className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--warning)]">
                <TriangleAlert className="h-3.5 w-3.5" /> Download failed
              </span>
            ) : null
          }
          extra={
            browser.status === "installing" ? (
              <div className="mt-3">
                <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--border)" }}>
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      background: "var(--accent)",
                      width: pct !== null ? `${pct}%` : "35%",
                    }}
                  />
                </div>
                <div className="mt-1.5 flex justify-between text-[11px] text-[var(--ink-3)]">
                  <span>
                    {browser.progress
                      ? `${Math.round(browser.progress.downloaded / 1e6)} MB${browser.progress.total ? ` of ${Math.round(browser.progress.total / 1e6)} MB` : ""}`
                      : "Starting…"}
                  </span>
                  {pct !== null && <span>{pct}%</span>}
                </div>
              </div>
            ) : browser.status === "failed" ? (
              <div
                className="mt-3 flex items-center justify-between gap-3 rounded-lg p-3"
                style={{ background: "var(--surface)" }}
              >
                <span className="font-mono text-[11px] text-[var(--ink-3)]">
                  {browser.error ?? "Download failed"}
                </span>
                <button
                  type="button"
                  onClick={() => void install()}
                  className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium text-white"
                  style={{ background: "var(--ink)", cursor: "pointer" }}
                >
                  Try again
                </button>
              </div>
            ) : browser.status === "optional" ? (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => void install()}
                  className="rounded-md border px-3 py-1.5 text-[12px] font-medium text-[var(--ink)]"
                  style={{ borderColor: "var(--border)", cursor: "pointer" }}
                >
                  Install browser
                </button>
              </div>
            ) : null
          }
        />
        <RuntimeRow
          icon={ShieldCheck}
          title="Command sandbox"
          desc="Keeps any commands agents run inside safe limits."
          right={
            sandbox === undefined ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--ink-3)]" />
            ) : sandbox === null ? (
              <span className="text-[12px] text-[var(--ink-3)]">Unknown</span>
            ) : sandbox.state === "available" ? (
              <ReadyBadge />
            ) : (
              <span className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--warning)]">
                <TriangleAlert className="h-3.5 w-3.5" />
                {sandbox.state === "experimental" ? "Experimental" : "Unavailable"}
              </span>
            )
          }
          extra={
            sandbox && sandbox.state !== "available" && sandbox.reason ? (
              <p
                className="mt-3 rounded-lg p-3 font-mono text-[11px] text-[var(--ink-3)]"
                style={{ background: "var(--surface)" }}
              >
                {sandbox.reason}
              </p>
            ) : undefined
          }
        />
        {(deps ?? []).map((dep) => (
          <RuntimeRow
            key={dep.id}
            icon={DEP_ICONS[dep.id] ?? Cpu}
            title={dep.label}
            chip="Optional"
            desc={dep.unlocks}
            right={<DepStatus dep={dep} />}
            extra={
              dep.status !== "ready" ? (
                <p className="mt-3 text-[11.5px] text-[var(--ink-3)]">
                  {dep.detail ? `${dep.detail} ` : ""}
                  Set it up later in Settings → General.
                </p>
              ) : undefined
            }
          />
        ))}
        {deps === null && (
          <RuntimeRow
            icon={Cpu}
            title="Optional tools"
            desc="Node.js, uv and Git power local MCP servers."
            right={
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--ink-3)]" />
            }
          />
        )}
        <RuntimeRow
          icon={Cpu}
          title="Ollama"
          chip="Optional"
          desc="Run AI models on this machine. Skip it if you will use an online AI service."
          right={
            <a
              href="https://ollama.com/download"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium text-[var(--ink)]"
              style={{ borderColor: "var(--border)" }}
            >
              Get Ollama
            </a>
          }
        />
      </div>
      {browser.status === "failed" && (
        <div className="mt-4">
          <CalloutBox icon={TriangleAlert} tone="warn">
            Agents can still chat and search. They just can't open websites
            until the browser is installed. You can finish this later in
            Settings, under Browser.
          </CalloutBox>
        </div>
      )}
      <p className="mt-4 text-[12px] text-[var(--ink-3)]">
        You can continue while the browser downloads. Agents that browse will
        wait for it.
      </p>
      <div className="mt-14 flex items-center justify-between">
        <BackButton onClick={onBack} />
        <PrimaryButton onClick={onDone}>
          {browser.status === "failed" ? "Continue without it" : "Continue"}
        </PrimaryButton>
      </div>
    </div>
  );
}

function ReadyBadge({ label = "Ready" }: { label?: string }) {
  return (
    <span className="flex items-center gap-1.5 text-[12px] font-medium" style={{ color: "var(--accent)" }}>
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full"
        style={{ background: "var(--accent)" }}
      >
        <Check className="h-3 w-3 text-white" />
      </span>
      {label}
    </span>
  );
}

const DEP_ICONS: Record<
  string,
  LucideIcon
> = {
  nodejs: SquareTerminal,
  uv: AppWindow,
  git: GitBranch,
};

function DepStatus({ dep }: { dep: RuntimeDependency }) {
  if (dep.status === "ready") {
    return (
      <ReadyBadge label={dep.version ? `Ready · ${dep.version}` : "Ready"} />
    );
  }
  if (dep.status === "missing") {
    return <span className="text-[12px] text-[var(--ink-3)]">Missing</span>;
  }
  return (
    <span className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--warning)]">
      <TriangleAlert className="h-3.5 w-3.5" />
      {dep.status === "incompatible" ? "Incompatible" : "Issue"}
    </span>
  );
}

function RuntimeRow({
  icon,
  title,
  chip,
  desc,
  right,
  extra,
}: {
  icon: LucideIcon;
  title: string;
  chip?: string;
  desc: string;
  right?: React.ReactNode;
  extra?: React.ReactNode;
}) {
  const Icon = icon;
  return (
    <div
      className="rounded-xl border bg-white p-4"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex items-start gap-3.5">
        <IconTile icon={Icon} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-[14px] font-semibold text-[var(--ink)]">{title}</p>
            {chip && (
              <span
                className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
              >
                {chip}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--ink-2)]">{desc}</p>
        </div>
        <div className="shrink-0 pt-1">{right}</div>
      </div>
      {extra}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Connect an AI — provider choice, key test, model                      */
/* ------------------------------------------------------------------ */

const SERVICE_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "deepseek", label: "DeepSeek" },
];

export interface ProviderResult {
  provider: Provider | null;
  model: string;
  skipped: boolean;
}

export function StepProvider({
  onDone,
  onBack,
}: {
  onDone: (r: ProviderResult) => void;
  onBack: () => void;
}) {
  const [choice, setChoice] = useState<"local" | "online" | "later">("online");
  const [service, setService] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState<Provider | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("");
  const [testing, setTesting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const resetConnection = () => {
    setConnected(false);
    setModels([]);
    setModel("");
  };

  const testConnection = async () => {
    setTesting(true);
    setError("");
    let created: Provider | null = null;
    try {
      const spec = SERVICE_OPTIONS.find((s) => s.value === service)!;
      created = await api.createProvider({
        name: spec.label,
        type: service,
        api_key: apiKey.trim(),
      });
      const r = await api.listModels(created.id);
      const first = r.models[0]?.name;
      // Listing models reads the offerings/catalog — it proves nothing about
      // the key. The honest check is the real 1-token probe.
      if (!first) {
        setProvider(created);
        setModels([]);
        setConnected(true); // no models to probe — key saved, verify on first run
        return;
      }
      const v = await api.validateProviderModel(created.id, first);
      if (!v.valid) {
        await api.deleteProvider(created.id).catch(() => {});
        setError(v.error || "The service rejected the key — check it and try again.");
        return;
      }
      setProvider(created);
      setModels(r.models);
      setModel(first);
      setConnected(true);
    } catch (e) {
      if (created) await api.deleteProvider(created.id).catch(() => {});
      setError(e instanceof Error ? e.message : "Connection failed.");
    } finally {
      setTesting(false);
    }
  };

  const connectOllama = async (): Promise<ProviderResult> => {
    const created = await api.createProvider({
      name: "Ollama",
      type: "ollama",
      base_url: "http://localhost:11434",
    });
    let picked = "";
    try {
      const r = await api.listModels(created.id);
      picked = r.models[0]?.name ?? "";
    } catch {
      // Ollama not answering — provider still created; agents stay unset.
    }
    return { provider: created, model: picked, skipped: false };
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (choice === "later") {
        onDone({ provider: null, model: "", skipped: true });
      } else if (choice === "local") {
        onDone(await connectOllama());
      } else {
        if (!connected || !provider) {
          setError("Test the connection first — it saves your key when it works.");
          setBusy(false);
          return;
        }
        onDone({ provider, model, skipped: false });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't continue.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <StepTitle>How should your agents think?</StepTitle>
      <StepSub>
        Pick where the AI runs. You can add more, or switch, later in Settings.
      </StepSub>
      <div className="mt-8 space-y-3">
        <ProviderOption
          selected={choice === "local"}
          onSelect={() => { setChoice("local"); resetConnection(); }}
          icon={Cpu}
          title="On this machine"
          chip="Most private"
          desc="Run models with Ollama. Nothing leaves your computer."
        />
        <ProviderOption
          selected={choice === "online"}
          onSelect={() => setChoice("online")}
          icon={Cloud}
          title="An online AI service"
          chip="Fastest to start"
          desc="Use OpenAI, Google Gemini, Anthropic or others with your own key."
        >
          {choice === "online" && (
            <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--border-soft)" }}>
              <div className="space-y-4">
                <Field label="Service">
                  <Select
                    value={service}
                    onChange={(v) => { setService(v); resetConnection(); }}
                    options={SERVICE_OPTIONS}
                    ariaLabel="Service"
                    className="w-full rounded-lg border px-3 py-2.5 text-[13px]"
                    align="left"
                  />
                </Field>
                <Field label="API key">
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => { setApiKey(e.target.value); resetConnection(); }}
                    placeholder="sk-…"
                    style={inputStyle}
                  />
                </Field>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void testConnection()}
                    disabled={testing || !apiKey.trim()}
                    className="flex items-center gap-2 rounded-lg border px-3.5 py-2 text-[12.5px] font-medium text-[var(--ink)]"
                    style={{
                      borderColor: "var(--border)",
                      cursor: testing || !apiKey.trim() ? "not-allowed" : "pointer",
                      opacity: testing || !apiKey.trim() ? 0.55 : 1,
                    }}
                  >
                    {testing ? (
                      <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    Test connection
                  </button>
                  {connected && (
                    <span className="flex items-center gap-1.5 text-[12px] font-medium" style={{ color: "var(--accent)" }}>
                      ● Connected
                    </span>
                  )}
                </div>
                {connected && models.length > 0 && (
                  <Field label="Model for your agents">
                    <Select
                      value={model}
                      onChange={setModel}
                      options={models.map((m) => ({
                        value: m.name,
                        label: m.display_name ?? m.name,
                      }))}
                      ariaLabel="Model for your agents"
                      className="w-full rounded-lg border px-3 py-2.5 text-[13px]"
                      align="left"
                    />
                  </Field>
                )}
                <p className="text-[11.5px] text-[var(--ink-3)]">
                  Your prompts are sent to this service. Your key stays on this
                  machine, encrypted.
                </p>
              </div>
            </div>
          )}
        </ProviderOption>
        <ProviderOption
          selected={choice === "later"}
          onSelect={() => { setChoice("later"); resetConnection(); }}
          icon={Sparkles}
          title="I'll decide later"
          chip="—"
          desc="You can look around first. Agents can't run until a model is connected."
        />
      </div>
      {error && (
        <p role="alert" className="mt-4 text-[12.5px] text-[var(--danger)]">
          {error}
        </p>
      )}
      <div className="mt-12 flex items-center justify-between">
        <BackButton onClick={onBack} />
        <PrimaryButton onClick={() => void submit()} disabled={busy}>
          {busy ? "Connecting…" : "Continue"}
        </PrimaryButton>
      </div>
    </div>
  );
}

function ProviderOption({
  selected,
  onSelect,
  icon,
  title,
  chip,
  desc,
  children,
}: {
  selected: boolean;
  onSelect: () => void;
  icon: LucideIcon;
  title: string;
  chip: string;
  desc: string;
  children?: React.ReactNode;
}) {
  const Icon = icon;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className="block w-full rounded-xl border bg-white p-4 text-left transition"
      style={{
        borderColor: selected ? "var(--accent)" : "var(--border)",
        borderWidth: selected ? 1.5 : 1,
        cursor: "pointer",
      }}
    >
      <div className="flex items-start gap-3.5">
        <span
          className="mt-1 flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-full border"
          style={{
            width: 18,
            height: 18,
            borderColor: selected ? "var(--accent)" : "var(--border)",
          }}
        >
          {selected && (
            <span
              className="rounded-full"
              style={{ width: 10, height: 10, background: "var(--accent)" }}
            />
          )}
        </span>
        <IconTile icon={Icon} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-[14px] font-semibold text-[var(--ink)]">{title}</p>
            <span
              className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
              style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
            >
              {chip}
            </span>
          </div>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--ink-2)]">{desc}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* What agents may do — Allow / Ask / Block                              */
/* ------------------------------------------------------------------ */

export type ToolChoice = "allow" | "ask" | "block";

export const TOOL_ROWS: {
  key: string;
  icon: LucideIcon;
  title: string;
  desc: string;
  caps: string[];
  recommended: ToolChoice;
}[] = [
  {
    key: "web",
    icon: Globe,
    title: "Search and read the web",
    desc: "Look things up and read pages.",
    caps: ["web_search", "web_fetch"],
    recommended: "allow",
  },
  {
    key: "browser",
    icon: AppWindow,
    title: "Control a browser",
    desc: "Open sites, click and fill in forms.",
    caps: ["browser_open", "browser_observe", "browser_act", "browser_extract", "browser_close"],
    recommended: "ask",
  },
  {
    key: "read",
    icon: FileText,
    title: "Read files",
    desc: "Read files you give it.",
    caps: ["read_file", "search_files"],
    recommended: "allow",
  },
  {
    key: "write",
    icon: Pencil,
    title: "Change files",
    desc: "Create, edit or delete files.",
    caps: ["write_file"],
    recommended: "ask",
  },
  {
    key: "terminal",
    icon: SquareTerminal,
    title: "Run commands",
    desc: "Run commands in a sandbox on this machine.",
    caps: ["terminal", "read_terminal", "close_terminal"],
    recommended: "ask",
  },
];

const CHOICES: { value: ToolChoice; label: string }[] = [
  { value: "allow", label: "Allow" },
  { value: "ask", label: "Ask" },
  { value: "block", label: "Block" },
];

/** Build a full grant list — `capabilities` is a whitelist on the backend,
 * so every listed capability needs a grant; unmapped ones carry their
 * registry defaults or they silently drop off the agent. */
export function buildGrantList(
  all: CapabilityInfo[],
  choices: Record<string, ToolChoice>,
) {
  const mapped = new Map<string, ToolChoice>();
  for (const row of TOOL_ROWS)
    for (const cap of row.caps) mapped.set(cap, choices[row.key] ?? row.recommended);
  return all.map((c) => {
    const choice = mapped.get(c.name);
    if (!choice)
      return {
        name: c.name,
        enabled: true,
        subject: "any" as const,
        require_approval: c.require_approval,
      };
    return {
      name: c.name,
      enabled: choice !== "block",
      subject: "any" as const,
      require_approval: choice === "ask",
    };
  });
}

export function StepPermissions({
  onDone,
  onBack,
}: {
  onDone: (choices: Record<string, ToolChoice>) => void;
  onBack: () => void;
}) {
  const [choices, setChoices] = useState<Record<string, ToolChoice>>(() =>
    Object.fromEntries(TOOL_ROWS.map((r) => [r.key, r.recommended])),
  );
  const isRecommended = TOOL_ROWS.every((r) => choices[r.key] === r.recommended);

  return (
    <div>
      <StepTitle>What are agents allowed to do?</StepTitle>
      <StepSub>
        CaberOS agents work through built-in tools. Choose which they can use
        freely, which need your OK, and which stay off.
      </StepSub>
      <div className="mt-8 rounded-xl border bg-white" style={{ borderColor: "var(--border)" }}>
        {TOOL_ROWS.map((row, i) => (
          <div
            key={row.key}
            className="flex items-center gap-3.5 px-4 py-3.5"
            style={{
              borderTop: i === 0 ? "none" : "1px solid var(--border-soft)",
            }}
          >
            <IconTile icon={row.icon} size={40} />
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-[var(--ink)]">
                {row.title}
              </p>
              <p className="mt-0.5 text-[12px] text-[var(--ink-2)]">{row.desc}</p>
            </div>
            <div
              className="flex shrink-0 rounded-lg p-0.5"
              style={{ background: "var(--border-soft, var(--border))" }}
            >
              {CHOICES.map((c) => {
                const active = choices[row.key] === c.value;
                return (
                  <button
                    key={c.value}
                    type="button"
                    onClick={() =>
                      setChoices((s) => ({ ...s, [row.key]: c.value }))
                    }
                    aria-pressed={active}
                    className="rounded-md px-3 py-1 text-[12px] font-medium transition"
                    style={{
                      cursor: "pointer",
                      background: active
                        ? c.value === "allow"
                          ? "var(--accent-bg)"
                          : c.value === "ask"
                            ? "var(--warning-bg, #F6EEDA)"
                            : "var(--surface)"
                        : "transparent",
                      color: active
                        ? c.value === "ask"
                          ? "var(--warning)"
                          : c.value === "allow"
                            ? "var(--accent)"
                            : "var(--ink)"
                        : "var(--ink-3)",
                    }}
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {/* Channel replies aren't a capability grant — they are governed by
            each channel's own approval policy, set when a channel is added. */}
        <div
          className="flex items-center gap-3.5 px-4 py-3.5"
          style={{ borderTop: "1px solid var(--border-soft)" }}
        >
          <IconTile icon={Send} size={40} />
          <div className="min-w-0 flex-1">
            <p className="text-[14px] font-semibold text-[var(--ink)]">
              Send messages
            </p>
            <p className="mt-0.5 text-[12px] text-[var(--ink-2)]">
              Reply through Telegram or Zalo.
            </p>
          </div>
          <span className="shrink-0 text-[11.5px] text-[var(--ink-3)]">
            Set per channel
          </span>
        </div>
      </div>
      <div className="mt-4 flex items-start justify-between gap-6">
        <p className="text-[12px] font-semibold" style={{ color: "var(--accent)" }}>
          {isRecommended
            ? "Recommended settings are selected."
            : "Custom settings are selected."}
        </p>
        <p className="text-[12px] leading-5 text-[var(--ink-2)]">
          Ask means the agent pauses and waits for your OK. Block turns it off.
        </p>
      </div>
      <p className="mt-1 text-[12px] text-[var(--ink-3)]">
        You can change any of this later in Settings, and for each agent.
      </p>
      <div className="mt-12 flex items-center justify-between">
        <BackButton onClick={onBack} />
        <PrimaryButton onClick={() => onDone(choices)}>Continue</PrimaryButton>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Meet your agents                                                      */
/* ------------------------------------------------------------------ */

const STARTER_IDEAS = [
  {
    label: "Researcher",
    prompt: "Build me a research specialist that digs into a topic and reports back with sources.",
  },
  {
    label: "Career analyst",
    prompt: "Build me a career analyst that tracks roles, companies, and market signals.",
  },
  {
    label: "Market watcher",
    prompt: "Build me a market watcher that follows prices and news on a schedule.",
  },
  {
    label: "Daily brief",
    prompt: "Build me a morning briefing agent that summarizes what changed overnight.",
  },
];

export function StepAgents({
  agents,
  onOpenChat,
  onDone,
  onBack,
}: {
  agents: Agent[];
  onOpenChat: (agentId: string, prompt?: string) => void;
  onDone: () => void;
  onBack: () => void;
}) {
  const builder = agents.find((a) => /builder/i.test(a.name)) ?? agents[1];
  return (
    <div>
      <StepTitle>Meet your agents</StepTitle>
      <StepSub>
        {agents.length > 0
          ? `${agents.length} agent${agents.length > 1 ? "s are" : " is"} already set up. Start with one, or build a specialist.`
          : "No agents yet — create one from Settings when you're ready."}
      </StepSub>
      <div className="mt-8 grid grid-cols-2 gap-4">
        {agents.map((agent, i) => (
          <div
            key={agent.id}
            className="rounded-xl border bg-white p-5"
            style={{ borderColor: "var(--border)" }}
          >
            <div className="flex items-center gap-3">
              <span
                className="flex h-11 w-11 items-center justify-center rounded-[12px] text-[17px] font-semibold"
                style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
              >
                {agent.name.charAt(0).toUpperCase()}
              </span>
              <p className="text-[16px] font-semibold text-[var(--ink)]">
                {agent.name}
              </p>
            </div>
            <p className="mt-3 line-clamp-3 min-h-[54px] text-[12.5px] leading-5 text-[var(--ink-2)]">
              {agent.persona || agent.task || "Your agent."}
            </p>
            <button
              type="button"
              onClick={() => onOpenChat(agent.id)}
              className="mt-3 flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-medium text-white"
              style={{ background: "var(--ink)", cursor: "pointer" }}
            >
              {i === 0 ? `Chat with ${agent.name}` : "Open chat"}
            </button>
          </div>
        ))}
      </div>
      {builder && (
        <div className="mt-8">
          <p className="text-[13px] font-semibold text-[var(--ink)]">
            Starter ideas
          </p>
          <p className="mt-1 text-[12px] text-[var(--ink-2)]">
            Tap one and {builder.name} starts with a ready-made request. You
            can change everything.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {STARTER_IDEAS.map((idea) => (
              <button
                key={idea.label}
                type="button"
                onClick={() => onOpenChat(builder.id, idea.prompt)}
                className="rounded-full border bg-white px-3.5 py-1.5 text-[12px] font-medium text-[var(--ink)] transition hover:bg-[var(--hover)]"
                style={{ borderColor: "var(--border)", cursor: "pointer" }}
              >
                {idea.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onOpenChat(builder.id, "Help me design a specialist agent.")}
              className="rounded-full border bg-white px-3.5 py-1.5 text-[12px] font-medium text-[var(--ink-2)]"
              style={{ borderColor: "var(--border)", cursor: "pointer" }}
            >
              More ideas ▾
            </button>
          </div>
        </div>
      )}
      <div className="mt-12 flex items-center justify-between">
        <BackButton onClick={onBack} />
        <PrimaryButton onClick={onDone}>Finish setup</PrimaryButton>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* You're all set — summary                                              */
/* ------------------------------------------------------------------ */

export interface ReadySummary {
  protected_: string;
  ai: string;
  permissions: string;
  agents: string;
}

export function StepReady({
  summary,
  firstAgentName,
  onChat,
  onToday,
}: {
  summary: ReadySummary;
  firstAgentName: string | null;
  onChat: () => void;
  onToday: () => void;
}) {
  const rows = [
    { label: "Workspace protected", value: summary.protected_ },
    { label: "AI connected", value: summary.ai },
    { label: "Permissions set", value: summary.permissions },
    { label: "Agents ready", value: summary.agents },
  ];
  return (
    <div className="flex flex-col items-center text-center">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-[20px]"
        style={{ background: "var(--accent)" }}
      >
        <Check className="h-8 w-8 text-white" />
      </div>
      <h1 className="mt-6 text-[30px] font-semibold tracking-tight text-[var(--ink)]">
        You're all set
      </h1>
      <p className="mt-2 text-[14px] text-[var(--ink-2)]">
        {firstAgentName
          ? `${firstAgentName} is ready. Say hello, and see how approvals feel.`
          : "Your workspace is ready."}
      </p>
      <div
        className="mt-8 w-full max-w-[480px] rounded-xl border bg-white text-left"
        style={{ borderColor: "var(--border)" }}
      >
        {rows.map((row, i) => (
          <div
            key={row.label}
            className="flex items-center gap-3 px-4 py-3"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--border-soft)" }}
          >
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
              style={{ background: "var(--accent)" }}
            >
              <Check className="h-3 w-3 text-white" />
            </span>
            <span className="flex-1 text-[13px] font-medium text-[var(--ink)]">
              {row.label}
            </span>
            <span className="text-[12px] text-[var(--ink-3)]">{row.value}</span>
          </div>
        ))}
      </div>
      <div className="mt-8 flex items-center gap-3">
        {firstAgentName && (
          <button
            type="button"
            onClick={onChat}
            className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13px] font-medium text-white"
            style={{ background: "var(--ink)", cursor: "pointer" }}
          >
            <Send className="h-3.5 w-3.5" /> Say hello to {firstAgentName}
          </button>
        )}
        <button
          type="button"
          onClick={onToday}
          className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2.5 text-[13px] font-medium text-[var(--ink)]"
          style={{ borderColor: "var(--border)", cursor: "pointer" }}
        >
          <Check className="h-4 w-4" /> Go to Today
        </button>
      </div>
    </div>
  );
}
