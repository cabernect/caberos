import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
/** Onboarding frame — two layouts per the fe_example designs:
 *  CenteredStage  — welcome + "all set" screens: centered column, no chrome.
 *  StepperShell   — the numbered steps: left pane with a vertical stepper,
 *                   right pane holds the step content and Back/Continue row. */

export interface StepDef {
  key: string;
  label: string;
}

export function CenteredStage({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="stage-fade fixed inset-0 z-[95] flex items-center justify-center overflow-y-auto"
      style={{ background: "var(--ground)" }}
    >
      <div className="mx-auto w-full max-w-[620px] px-8 py-16">{children}</div>
    </div>
  );
}

/** Direction-aware step swap: the leaving step slides out while the
 * incoming one slides in from the travel direction (forward = from the
 * right, Back = from the left). The outgoing copy is a remounted snapshot,
 * so per-step state resets during the ~300ms exit — accepted trade-off. */
export function StepTransition({
  step,
  children,
}: {
  step: number;
  children: React.ReactNode;
}) {
  const [leaving, setLeaving] = useState<{
    step: number;
    node: React.ReactNode;
  } | null>(null);
  const dirRef = useRef<1 | -1>(1);
  const prevRef = useRef({ step, node: children });

  if (prevRef.current.step !== step) {
    dirRef.current = step > prevRef.current.step ? 1 : -1;
    setLeaving(prevRef.current);
    prevRef.current = { step, node: children };
  }

  useEffect(() => {
    if (!leaving) return;
    const t = window.setTimeout(() => setLeaving(null), 300);
    return () => window.clearTimeout(t);
  }, [leaving]);

  const dir = dirRef.current;
  return (
    <div className="relative">
      {leaving && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-x-0 top-0 ${
            dir === 1 ? "ob-step-out-fwd" : "ob-step-out-back"
          }`}
        >
          {leaving.node}
        </div>
      )}
      <div key={step} className={dir === 1 ? "ob-step-in-fwd" : "ob-step-in-back"}>
        {children}
      </div>
    </div>
  );
}

export function StepperShell({
  steps,
  current,
  asideFooter,
  children,
}: {
  steps: StepDef[];
  current: number;
  asideFooter?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className="stage-fade fixed inset-0 z-[95] flex"
      style={{ background: "var(--ground)" }}
    >
      <aside
        className="flex w-[360px] shrink-0 flex-col px-8 pb-8 pt-8"
        style={{ background: "var(--surface)", borderRight: "1px solid var(--border-soft)" }}
      >
        <div className="flex items-center gap-2.5">
          <img src="/_logo-mark.svg" alt="CaberOS" className="h-8 w-8" />
          <span className="text-[15px] font-semibold text-[var(--ink)]">
            CaberOS
          </span>
        </div>
        <ol className="mt-12 space-y-0">
          {steps.map((step, i) => {
            const done = i < current;
            const active = i === current;
            return (
              <li key={step.key} className="relative flex gap-3 pb-8 last:pb-0">
                {i < steps.length - 1 && (
                  <span
                    aria-hidden
                    className="absolute left-[13px] top-7 h-[calc(100%-14px)] w-px"
                    style={{ background: "var(--border)" }}
                  />
                )}
                <span
                  className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-medium transition-colors duration-300"
                  style={{
                    background: done ? "var(--accent)" : "var(--surface)",
                    color: done
                      ? "white"
                      : active
                        ? "var(--accent)"
                        : "var(--ink-3)",
                    border: `1.5px solid ${done || active ? "var(--accent)" : "var(--border)"}`,
                  }}
                >
                  {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </span>
                <span
                  className="pt-1 text-[13px] font-medium transition-colors duration-300"
                  style={{
                    color: done || active ? "var(--ink)" : "var(--ink-3)",
                  }}
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ol>
        <div className="mt-auto text-[12px] leading-5 text-[var(--ink-3)]">
          <p>Setup takes about two minutes.</p>
          <p>Everything stays on this machine.</p>
          <a
            href="https://github.com/cabernect/caberos/tree/main/docs"
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block font-medium"
            style={{ color: "var(--accent)" }}
          >
            Read the guide
          </a>
          {asideFooter}
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto px-14 pb-8 pt-12">
        <div className="mx-auto max-w-[620px]">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--accent)]">
            Step {current + 1} of {steps.length}
          </p>
          {children}
        </div>
      </main>
    </div>
  );
}
