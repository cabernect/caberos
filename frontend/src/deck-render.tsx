import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import type { DeckSpec } from "./lib/types";
import { DeckSlideCanvas } from "./components/previews/renderers";
import "./index.css";
import "./deck-print.css";

declare global {
  interface Window {
    __renderDeck?: (spec: DeckSpec, indices: number[]) => Promise<{errors: string[]}>;
  }
}

const root = createRoot(document.getElementById("root")!);
window.__renderDeck = async (spec, indices) => {
  flushSync(() => root.render(<>{indices.map(index => <section className="deck-print-slide" key={spec.slides[index].id}>
    <DeckSlideCanvas slide={spec.slides[index]} spec={spec} />
  </section>)}</>));
  await document.fonts.ready;
  const errors: string[] = [];
  await Promise.all(Array.from(document.images, async image => {
    try { await image.decode(); } catch { errors.push("An embedded image could not be decoded"); }
  }));
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  document.querySelectorAll<HTMLElement>(".deck-print-slide").forEach((frame, order) => {
    const bounds = frame.getBoundingClientRect();
    frame.querySelectorAll<HTMLElement>("[data-block]").forEach(block => {
      const rect = block.getBoundingClientRect();
      if (rect.bottom > bounds.top + 670 || rect.top < bounds.top ||
          rect.left < bounds.left || rect.right > bounds.right ||
          block.scrollWidth > block.clientWidth + 1) {
        errors.push(`Slide ${indices[order] + 1}: block ${block.dataset.block} overflows the slide/footer area`);
      }
    });
  });
  return {errors};
};
