import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import {
  dismissAllIntros,
  getSeenIntros,
  introsDismissed,
  markIntroSeen,
  onGuidanceChange,
} from "./guidanceState";
import type { PageIntroDef } from "./tourStops";

/** Inline page-intro card per fe_example "Page intro cards": olive card at
 * the TOP of the page, pushing content down — never overlaid. Page-name
 * eyebrow, title, check-marked facts, Got it / Learn more / Don't show
 * hints again (far right), and an × that dismisses just this page's card.
 * mb-4 keeps a consistent gap to whatever content follows.
 *
 * Mounted inside each page's own layout (not globally) so it sits above
 * the content it introduces. */
export function PageIntro({ def }: { def: PageIntroDef | undefined }) {
  const [, setTick] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => onGuidanceChange(() => setTick((t) => t + 1)), []);

  if (!def || dismissed || introsDismissed() || getSeenIntros().has(def.key))
    return null;

  const seen = () => {
    markIntroSeen(def.key);
    setDismissed(true);
  };

  return (
    <section
      aria-label={`New to ${def.eyebrow}`}
      className="mb-4 rounded-xl px-5 pb-4 pt-4"
      style={{ background: "var(--accent-bg)" }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--accent)]">
            {def.eyebrow}
          </p>
          <h2 className="mt-0.5 text-[18px] font-semibold tracking-tight text-[var(--ink)]">
            {def.title}
          </h2>
          <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">{def.sub}</p>
        </div>
        <button
          type="button"
          onClick={seen}
          aria-label={`Dismiss ${def.title} hint`}
          className="cursor-pointer rounded p-0.5 text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-4 flex flex-wrap gap-x-10 gap-y-2">
        {def.facts.map((fact) => (
          <div key={fact} className="flex items-start gap-2">
            <Check
              className="mt-0.5 h-3.5 w-3.5 shrink-0"
              style={{ color: "var(--accent)" }}
            />
            <p className="text-[12.5px] font-medium leading-5 text-[var(--ink)]">
              {fact}
            </p>
          </div>
        ))}
      </div>
      <div className="mt-3.5 flex items-center gap-4">
        <button
          type="button"
          onClick={seen}
          className="flex cursor-pointer items-center gap-1.5 rounded-lg px-4 py-2 text-[12.5px] font-medium text-white"
          style={{ background: "var(--ink)" }}
        >
          <Check className="h-3.5 w-3.5" /> Got it
        </button>
        <a
          href="https://github.com/cabernect/caberos/tree/main/docs"
          target="_blank"
          rel="noreferrer"
          className="text-[12.5px] font-medium"
          style={{ color: "var(--accent)" }}
        >
          Learn more
        </a>
        <button
          type="button"
          onClick={dismissAllIntros}
          className="ml-auto cursor-pointer text-[12px] text-[var(--ink-3)]"
          style={{ background: "none", border: "none" }}
        >
          Don't show hints again
        </button>
      </div>
    </section>
  );
}
