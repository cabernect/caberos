import { useEffect, useState } from "react";
import type { DeckSlide } from "@/lib/types";

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Reveal order follows source order, including blocks assigned to columns. */
export function revealSteps(slide: DeckSlide) {
  let total = 0;
  const blocks = (slide.blocks ?? []).map((block) => {
    const count = block.reveal === "items" ? (block.items?.length ?? 0) : block.reveal ? 1 : 0;
    const start = total;
    total += count;
    return { start, count };
  });
  return { blocks, total };
}
