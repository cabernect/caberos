import { useCallback, useState } from "react";

/** Drag-to-resize hook for a right-docked panel: drag its left edge to
 * resize. Clamps [min, max], persists to localStorage when storageKey is
 * given, and locks cursor/selection while dragging so text doesn't get
 * selected mid-drag. */
export function useResizableWidth({
  initial,
  min,
  max,
  storageKey,
}: {
  initial: number;
  min: number;
  max: number;
  storageKey?: string;
}) {
  const [width, setWidth] = useState(() => {
    if (!storageKey) return initial;
    const saved = Number(localStorage.getItem(storageKey));
    return saved >= min && saved <= max ? saved : initial;
  });
  const [dragging, setDragging] = useState(false);

  const startResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = width;
      // Panel hugs the right edge — dragging left grows it.
      const onMove = (ev: MouseEvent) => {
        const ceiling = Math.min(max, window.innerWidth - 320);
        setWidth(Math.min(ceiling, Math.max(min, startWidth + (startX - ev.clientX))));
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        setDragging(false);
        if (storageKey) {
          setWidth((w) => {
            localStorage.setItem(storageKey, String(w));
            return w;
          });
        }
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      setDragging(true);
    },
    [width, min, max, storageKey],
  );

  return { width, dragging, startResize };
}
