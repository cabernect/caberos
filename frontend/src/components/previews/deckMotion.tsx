import { useEffect, useRef, type ReactNode } from "react";
import type { DeckEffect } from "@/lib/types";

export function DeckMotion({ children, effect, visible = true, reverse = false, className }: {
  children: ReactNode;
  effect?: DeckEffect;
  visible?: boolean;
  reverse?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const kind = effect?.type ?? "none";
  const duration = effect?.duration_ms ?? 300;
  useEffect(() => {
    const el = ref.current;
    if (!el || !visible || kind === "none" || duration === 0 || !el.animate) return;
    const transform = kind === "slide" ? `translateX(${reverse ? -100 : 100}px)`
      : kind === "rise" ? "translateY(24px)" : "none";
    const animation = el.animate(
      [{ opacity: 0, transform }, { opacity: 1, transform: "none" }],
      { duration, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
    );
    return () => animation.cancel();
  }, [visible, kind, duration, reverse]);
  return (
    <div
      ref={ref}
      className={className}
      aria-hidden={!visible || undefined}
      style={{ visibility: visible ? undefined : "hidden" }}
      data-deck-effect={kind}
    >
      {children}
    </div>
  );
}
