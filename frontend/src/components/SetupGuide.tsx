import { useEffect, useState } from "react";
import { ArrowRight, Check, CircleHelp, ExternalLink, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  dismissSetupGuide,
  getSetupGuideAgentId,
  isSetupGuideDismissed,
  getSetupGuidePhase,
  setSetupGuidePhase,
  type SetupGuidePhase,
} from "./setupGuideState";

interface SetupGuideProps {
  setupIncomplete: boolean;
}

export function SetupGuide({ setupIncomplete }: SetupGuideProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<SetupGuidePhase>(() => getSetupGuidePhase());
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const sync = () => {
      setPhase(getSetupGuidePhase());
      setDismissed(isSetupGuideDismissed());
    };
    sync();
    window.addEventListener("caberos-setup-guide-change", sync);
    return () => window.removeEventListener("caberos-setup-guide-change", sync);
  }, []);

  if (dismissed || (!setupIncomplete && phase < 3)) return null;

  const onAgents = location.pathname === "/agents";
  const onChat = location.pathname.startsWith("/agents/") && location.pathname.endsWith("/chat");
  const onSettings = location.pathname === "/settings";
  const visible = (phase === 0 && onAgents) || (phase === 1 && onChat) || (phase === 2 && onSettings) || (phase === 3 && onChat);
  if (!visible) return null;

  const copy = phase === 0
    ? {
        eyebrow: "Step 1 of 4",
        title: "Start with Caber",
        body: "Caber is your everyday assistant. Open it first — we’ll set up everything you need from there.",
        action: "Open Caber",
      }
    : phase === 1
      ? {
          eyebrow: "Step 2 of 4",
          title: "Connect a model",
          body: "Caber needs a provider before it can answer. Add an API key, or connect a local provider such as Ollama.",
          action: "Configure provider",
        }
      : phase === 2
        ? {
            eyebrow: "Step 3 of 4",
            title: "Add your provider",
            body: "Use the Providers tab to add an API key, or connect a local Ollama instance. Your key stays encrypted on this machine.",
            action: "Return to Caber",
          }
        : {
            eyebrow: "Step 4 of 4",
            title: "Configure, then chat",
            body: "If Caber still needs a model, use the banner above the composer to configure it. Then send your first message.",
            action: "Finish guide",
          };

  const handleAction = () => {
    if (phase === 0) {
      const caber = document.querySelector<HTMLElement>('[data-agent-name="Caber"]');
      caber?.focus();
      caber?.click();
      return;
    }
    if (phase === 1) {
      setSetupGuidePhase(2);
      navigate("/settings?guide=provider");
      return;
    }
    if (phase === 2) {
      setSetupGuidePhase(3);
      navigate(`/agents/${getSetupGuideAgentId()}/chat`);
      return;
    }
    dismissSetupGuide();
  };

  return (
    <aside
      aria-label="CaberOS setup guide"
      className="fixed bottom-6 right-6 z-[80] w-[min(360px,calc(100vw-32px))] rounded-xl border p-5 shadow-xl"
      style={{ background: "var(--white)", borderColor: "var(--accent)", boxShadow: "0 12px 36px rgba(28, 28, 28, 0.16)" }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--accent-bg)" }}>
            {phase === 3 ? <Check className="h-4 w-4" style={{ color: "var(--accent)" }} /> : <CircleHelp className="h-4 w-4" style={{ color: "var(--accent)" }} />}
          </div>
          <div>
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--accent)]">{copy.eyebrow}</p>
            <h2 className="mt-1 text-[15px] font-semibold text-[var(--ink)]">{copy.title}</h2>
          </div>
        </div>
        <button type="button" onClick={dismissSetupGuide} aria-label="Close setup guide" className="rounded p-1 text-[var(--ink-3)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]" style={{ cursor: "pointer" }}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-4 text-[13px] leading-6 text-[var(--ink-2)]">{copy.body}</p>
      <div className="mt-5 flex items-center justify-between gap-3">
        <div className="flex gap-1.5" aria-label={`Setup progress, step ${phase + 1} of 4`}>
          {[0, 1, 2, 3].map((item) => <span key={item} className="h-1.5 w-7 rounded-full" style={{ background: item <= phase ? "var(--accent)" : "var(--border)" }} />)}
        </div>
        <button type="button" onClick={handleAction} className="flex items-center gap-2 rounded-md px-3 py-2 text-[12px] font-medium text-white transition-opacity hover:opacity-90" style={{ background: "var(--accent)", cursor: "pointer" }}>
          {copy.action} {phase === 0 || phase === 1 ? <ArrowRight className="h-3.5 w-3.5" /> : phase === 2 ? <ExternalLink className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
        </button>
      </div>
    </aside>
  );
}
