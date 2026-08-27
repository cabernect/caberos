import { useEffect, useState } from "react";
import { ArrowRight, Check, KeyRound, LoaderCircle, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent, ModelInfo, Provider } from "@/lib/types";

interface OnboardingProps {
  providers: Provider[];
  agents: Agent[];
  onComplete: () => void;
}

const ONBOARDING_STEP_KEY = "caberos_onboarding_step";
const ONBOARDING_AGENT_KEY = "caberos_onboarding_agent_name";

function savedNumber(key: string, fallback: number) {
  try {
    const value = Number(localStorage.getItem(key));
    return Number.isFinite(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

export function Onboarding({ providers, agents, onComplete }: OnboardingProps) {
  const defaultStep = providers.some((item) => item.has_key) && agents.length === 0 ? 2 : 0;
  const [step, setStep] = useState(() => Math.min(3, Math.max(defaultStep, savedNumber(ONBOARDING_STEP_KEY, defaultStep))));
  const [providerName, setProviderName] = useState("OpenAI");
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState<Provider | null>(
    providers.find((item) => item.has_key) || null,
  );
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("");
  const [agentName, setAgentName] = useState(() => {
    try { return localStorage.getItem(ONBOARDING_AGENT_KEY) || "Caber"; } catch { return "Caber"; }
  });
  const [document, setDocument] = useState<File | null>(null);
  const [backup, setBackup] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      localStorage.setItem(ONBOARDING_STEP_KEY, String(step));
      localStorage.setItem(ONBOARDING_AGENT_KEY, agentName);
    } catch {
      // Resume state is best effort when storage is unavailable.
    }
  }, [agentName, step]);

  useEffect(() => {
    if (!provider) return;
    api.listModels(provider.id).then((result) => {
      setModels(result.models);
      if (!model && result.models[0]) setModel(result.models[0].name);
    }).catch(() => setModels([]));
  }, [provider, model]);

  const saveProvider = async () => {
    if (!apiKey.trim()) {
      setError("Enter an API key to continue, or choose Ollama if it is running locally.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await api.createProvider({
        name: providerName.trim() || "OpenAI",
        type: "openai",
        api_key: apiKey.trim(),
      });
      setProvider(created);
      setStep(2);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Provider validation failed. Check the key and try again.");
    } finally {
      setBusy(false);
    }
  };

  const saveAgent = async () => {
    if (!provider || !model.trim()) {
      setError("Select a model before creating your first agent.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createAgent({
        name: agentName.trim() || "Caber",
        provider_id: provider.id,
        model_name: model.trim(),
      });
      setStep(3);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the first agent.");
    } finally {
      setBusy(false);
    }
  };

  const finishSetup = async () => {
    setBusy(true);
    setError("");
    try {
      if (backup) await api.importBackup(backup);
      if (document) await api.uploadKnowledgeDocument(document);
      try {
        localStorage.removeItem(ONBOARDING_STEP_KEY);
        localStorage.removeItem(ONBOARDING_AGENT_KEY);
      } catch {
        // Ignore unavailable browser storage.
      }
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Optional setup import failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/20 px-4">
      <section
        aria-labelledby="onboarding-title"
        className="w-full max-w-lg rounded-xl border p-7 shadow-2xl"
        style={{ background: "var(--white)", borderColor: "var(--border)" }}
      >
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg" style={{ background: "var(--accent)" }}>
            {step === 0 ? <Sparkles className="h-5 w-5 text-white" /> : <KeyRound className="h-5 w-5 text-white" />}
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--ink-3)]">First setup</p>
            <h1 id="onboarding-title" className="text-xl font-semibold text-[var(--ink)]">Set up your local agent</h1>
          </div>
        </div>

        <div className="mb-7 flex gap-2" aria-label="Onboarding progress">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-1 flex-1 rounded-full" style={{ background: item <= step ? "var(--accent)" : "var(--border)" }} />
          ))}
        </div>

        {step === 0 && (
          <div>
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">Private by default</h2>
            <p className="mt-2 text-[13px] leading-6 text-[var(--ink-2)]">
              CaberOS keeps your agents, credentials, memory, and workspace on this machine. We will configure one model and create your first agent now.
            </p>
            <button type="button" onClick={() => setStep(provider ? 2 : 1)} className="mt-7 flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-medium text-white" style={{ background: "var(--accent)", cursor: "pointer" }}>
              Get started <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        )}

        {step === 1 && (
          <form onSubmit={(event) => { event.preventDefault(); void saveProvider(); }}>
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">Connect a model provider</h2>
            <p className="mt-2 text-[13px] text-[var(--ink-2)]">Your key is encrypted before it is stored. Ollama can be added from Settings for a local-only model.</p>
            <label className="mt-5 block text-[12px] font-medium text-[var(--ink-2)]">Provider name<input value={providerName} onChange={(event) => setProviderName(event.target.value)} className="mt-1 w-full rounded-md border px-3 py-2 text-[13px]" style={{ borderColor: "var(--border)" }} /></label>
            <label className="mt-3 block text-[12px] font-medium text-[var(--ink-2)]">API key<input autoFocus type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="mt-1 w-full rounded-md border px-3 py-2 text-[13px]" style={{ borderColor: "var(--border)" }} /></label>
            {error && <p role="alert" className="mt-3 text-[12px] text-[var(--danger)]">{error}</p>}
            <button type="submit" disabled={busy} className="mt-6 flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-medium text-white" style={{ background: "var(--accent)", cursor: busy ? "wait" : "pointer" }}>
              {busy && <LoaderCircle className="h-4 w-4 animate-spin" />} Validate and continue
            </button>
          </form>
        )}

        {step === 2 && (
          <form onSubmit={(event) => { event.preventDefault(); void saveAgent(); }}>
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">Create your first agent</h2>
            <p className="mt-2 text-[13px] text-[var(--ink-2)]">Choose a model to power your first conversation.</p>
            <label className="mt-5 block text-[12px] font-medium text-[var(--ink-2)]">Agent name<input value={agentName} onChange={(event) => setAgentName(event.target.value)} className="mt-1 w-full rounded-md border px-3 py-2 text-[13px]" style={{ borderColor: "var(--border)" }} /></label>
            <label className="mt-3 block text-[12px] font-medium text-[var(--ink-2)]">Model<input list="onboarding-models" value={model} onChange={(event) => setModel(event.target.value)} placeholder="Enter or select a model" className="mt-1 w-full rounded-md border px-3 py-2 text-[13px]" style={{ borderColor: "var(--border)" }} /><datalist id="onboarding-models">{models.map((item) => <option key={item.id} value={item.name} />)}</datalist></label>
            {models.length === 0 && <p className="mt-2 text-[12px] text-[var(--ink-3)]">No models were discovered. You can enter the model name manually.</p>}
            {error && <p role="alert" className="mt-3 text-[12px] text-[var(--danger)]">{error}</p>}
            <button type="submit" disabled={busy || !model.trim()} className="mt-6 flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-medium text-white" style={{ background: "var(--accent)", cursor: busy || !model.trim() ? "not-allowed" : "pointer", opacity: busy || !model.trim() ? 0.6 : 1 }}>
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Continue
            </button>
          </form>
        )}

        {step === 3 && (
          <div>
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">Bring in existing data</h2>
            <p className="mt-2 text-[13px] text-[var(--ink-2)]">Both options are optional. You can do this later from Settings or Knowledge Vault.</p>
            <label className="mt-5 block text-[12px] font-medium text-[var(--ink-2)]">CaberOS backup<input type="file" accept=".zip,application/zip" onChange={(event) => setBackup(event.target.files?.[0] || null)} className="mt-1 block w-full text-[12px]" /></label>
            <label className="mt-4 block text-[12px] font-medium text-[var(--ink-2)]">Initial knowledge document<input type="file" accept=".md,.txt,.pdf,.docx,.xlsx" onChange={(event) => setDocument(event.target.files?.[0] || null)} className="mt-1 block w-full text-[12px]" /></label>
            {error && <p role="alert" className="mt-3 text-[12px] text-[var(--danger)]">{error}</p>}
            <div className="mt-6 flex gap-2">
              <button type="button" onClick={() => void finishSetup()} disabled={busy} className="flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-medium text-white" style={{ background: "var(--accent)", cursor: busy ? "wait" : "pointer" }}>{busy && <LoaderCircle className="h-4 w-4 animate-spin" />} Finish setup</button>
              <button type="button" onClick={onComplete} disabled={busy} className="rounded-md border px-4 py-2 text-[13px] text-[var(--ink-2)]" style={{ borderColor: "var(--border)", cursor: busy ? "not-allowed" : "pointer" }}>Skip</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
