import { useEffect, useLayoutEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";
import { setTourState } from "./guidanceState";
import { TOUR_STEPS } from "./tourStops";

/** Three-step spotlight tour on the Today page, per fe_example/Spotlight
 * tour images: the rest of the page dims, an olive ring hugs the whole
 * region (sidebar / Needs-you / composer), and a small tailed card sits
 * beside it. Never navigates; Esc skips. */
const CARD_W = 280;
const CARD_H_EST = 170;
const GAP = 16;

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function measure(anchor: string): Rect | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

export function TourSpotlight() {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const step = TOUR_STEPS[index];
  const last = index === TOUR_STEPS.length - 1;

  useLayoutEffect(() => {
    const find = () => setRect(measure(step.anchor));
    find();
    window.addEventListener("resize", find);
    window.addEventListener("scroll", find, true);
    return () => {
      window.removeEventListener("resize", find);
      window.removeEventListener("scroll", find, true);
    };
  }, [step.anchor]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTourState("skipped");
      else if (e.key === "ArrowRight" && !last) setIndex((i) => i + 1);
      else if (e.key === "ArrowLeft" && index > 0) setIndex((i) => i - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, last]);

  const next = () => (last ? setTourState("done") : setIndex((i) => i + 1));

  // Card placement: preferred side, flipped when there is no room.
  let card: React.CSSProperties = { left: 24, top: 24 };
  let side = step.cardSide;
  if (rect) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const roomBelow = vh - (rect.top + rect.height) - GAP;
    const roomAbove = rect.top - GAP;
    if (side === "below" && roomBelow < CARD_H_EST && roomAbove > CARD_H_EST)
      side = "above";
    if (side === "above" && roomAbove < CARD_H_EST && roomBelow > CARD_H_EST)
      side = "below";

    if (side === "right") {
      card = {
        left: rect.left + rect.width + GAP,
        top: Math.min(
          Math.max(24, rect.top + 8),
          vh - CARD_H_EST - 24,
        ),
      };
    } else if (side === "below") {
      card = {
        left: Math.min(
          Math.max(24, rect.left + rect.width - CARD_W - 8),
          vw - CARD_W - 24,
        ),
        top: rect.top + rect.height + GAP,
      };
    } else {
      card = {
        left: Math.min(
          Math.max(24, rect.left + rect.width - CARD_W - 8),
          vw - CARD_W - 24,
        ),
        top: rect.top - CARD_H_EST - GAP,
      };
    }
  }

  // Tail: a small rotated square on the card edge that faces the region.
  const tailStyle: React.CSSProperties = {
    position: "absolute",
    width: 12,
    height: 12,
    background: "var(--white)",
    transform: "rotate(45deg)",
    borderLeft: "1px solid var(--accent)",
    borderTop: "1px solid var(--accent)",
  };
  if (rect && side === "right") {
    Object.assign(tailStyle, { left: -7, top: 28 });
  } else if (rect && side === "below") {
    Object.assign(tailStyle, { top: -7, right: 32, transform: "rotate(45deg)" });
  } else if (rect) {
    Object.assign(tailStyle, {
      bottom: -7,
      right: 32,
      transform: "rotate(225deg)",
    });
  }

  return (
    <>
      {/* Dim everything except the spotlighted region — the cutout is the
          region's own rect casting an enormous dark box-shadow. */}
      {rect ? (
        <div
          aria-hidden
          className="pointer-events-none fixed z-[84] rounded-[10px]"
          style={{
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            boxShadow: "0 0 0 9999px rgba(24, 24, 20, 0.55)",
            border: "1.5px solid var(--accent)",
          }}
        />
      ) : (
        <div
          aria-hidden
          className="fixed inset-0 z-[84]"
          style={{ background: "rgba(24, 24, 20, 0.55)" }}
        />
      )}
      <aside
        aria-label={`Tour step ${index + 1} of ${TOUR_STEPS.length}: ${step.title}`}
        className="fixed z-[86] rounded-xl border p-4"
        style={{
          ...card,
          width: CARD_W,
          background: "var(--white)",
          borderColor: "var(--accent)",
          boxShadow: "0 12px 36px rgba(28,28,28,0.2)",
        }}
      >
        {rect && <span aria-hidden style={tailStyle} />}
        <div className="flex items-start justify-between gap-3">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--accent)]">
            {step.eyebrow}
          </p>
          <button
            type="button"
            onClick={() => setTourState("skipped")}
            aria-label="Skip tour"
            className="cursor-pointer rounded p-1 text-[var(--ink-3)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        <h2 className="mt-1 text-[14px] font-semibold text-[var(--ink)]">
          {step.title}
        </h2>
        <p className="mt-1.5 text-[12px] leading-5 text-[var(--ink-2)]">
          {step.body}
        </p>
        <div className="mt-3.5 flex items-center justify-between">
          <div className="flex gap-1" aria-hidden>
            {TOUR_STEPS.map((_, i) => (
              <span
                key={i}
                className="h-1 w-4 rounded-full"
                style={{
                  background: i <= index ? "var(--accent)" : "var(--border)",
                }}
              />
            ))}
          </div>
          <div className="flex gap-1.5">
            {index > 0 && (
              <button
                type="button"
                onClick={() => setIndex((i) => i - 1)}
                className="flex cursor-pointer items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-medium text-[var(--ink-2)]"
                style={{ borderColor: "var(--border)" }}
              >
                <ArrowLeft className="h-3 w-3" /> Back
              </button>
            )}
            <button
              type="button"
              onClick={next}
              className="flex cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              {last ? "Got it" : "Next"}
              {last ? <Check className="h-3 w-3" /> : <ArrowRight className="h-3 w-3" />}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
