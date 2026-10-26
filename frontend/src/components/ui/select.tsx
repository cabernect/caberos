import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  /** Trigger styling — mirrors the className callers used on <select>. */
  className?: string;
  /** Extra classes for the popover panel (text size, whitespace…). */
  panelClassName?: string;
  /** Which trigger edge the panel hugs. Right suits trailing row controls. */
  align?: "left" | "right";
  onClick?: (e: React.MouseEvent) => void;
  ariaLabel?: string;
  title?: string;
}

interface PanelPos {
  top: number;
  left?: number;
  right?: number;
  minWidth: number;
}

/** Styled dropdown replacing native <select> — identical rendering in Chrome
 * and WKWebView. The panel is portaled to <body> so it is never clipped by
 * overflow containers, tracks its trigger on scroll, and flips upward when
 * there is no room below. */
export function Select({
  value,
  onChange,
  options,
  placeholder = "— Select —",
  disabled,
  className = "",
  panelClassName = "",
  align = "right",
  onClick,
  ariaLabel,
  title,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<PanelPos | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const updatePos = () => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (!r) return;
    setPos({
      top: r.bottom + 4,
      left: align === "left" ? r.left : undefined,
      right: align === "right" ? window.innerWidth - r.right : undefined,
      minWidth: r.width,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePos();
    const follow = () => updatePos();
    document.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => {
      document.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, align]);

  // Flip upward when the panel would run past the viewport bottom.
  useLayoutEffect(() => {
    if (!open || !pos) return;
    const panel = panelRef.current;
    const r = triggerRef.current?.getBoundingClientRect();
    if (!panel || !r) return;
    const panelH = panel.offsetHeight;
    const flipTop = r.top - 4 - panelH;
    if (
      r.bottom + 4 + panelH > window.innerHeight - 8 &&
      flipTop > 8 &&
      pos.top !== flipTop
    ) {
      setPos({ ...pos, top: flipTop });
    }
  }, [open, pos]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = options.find((o) => o.value === value);

  return (
    <div ref={rootRef} className={`relative ${className.includes("w-full") ? "w-full" : "inline-block"}`}>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        title={title}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) setOpen((v) => !v);
        }}
        className={`flex cursor-pointer items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      >
        <span className="truncate">{selected?.label ?? placeholder}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-3" />
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={panelRef}
            role="listbox"
            className={`fixed z-[100] max-h-56 overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg ${panelClassName}`}
            style={{
              top: pos.top,
              left: pos.left,
              right: pos.right,
              minWidth: pos.minWidth,
            }}
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-[11px] text-ink-2 transition-colors hover:bg-track hover:text-ink"
                onClick={(e) => {
                  e.stopPropagation();
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                <Check
                  className={`h-3 w-3 shrink-0 text-accent ${option.value === value ? "opacity-100" : "opacity-0"}`}
                />
                <span className="truncate">{option.label}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
