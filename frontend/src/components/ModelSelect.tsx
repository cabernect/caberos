import { useEffect, useRef, useState, useId } from "react";
import { ChevronDown, Check, Search } from "lucide-react";
import type { ModelInfo } from "@/lib/types";

interface ModelSelectProps {
  value: string;
  onChange: (value: string) => void;
  models: ModelInfo[];
  loading?: boolean;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * Searchable model dropdown.
 *
 * - When models are discovered, shows a filterable list.
 * - Always allows typing a custom model name (for providers without discovery).
 * - Keyboard: Up/Down to navigate, Enter to select, Esc to close.
 */
export function ModelSelect({
  value,
  onChange,
  models,
  loading = false,
  placeholder = "Search or type a model name…",
  disabled = false,
}: ModelSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Filter models by query
  const filtered = models.filter((m) =>
    m.name.toLowerCase().includes(query.toLowerCase()),
  );

  // Sync query with value when opening
  useEffect(() => {
    if (open) {
      setQuery(value);
      setHighlighted(0);
      // Focus the input after opening
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectModel = (name: string) => {
    onChange(name);
    setOpen(false);
    setQuery("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && filtered[highlighted]) {
        selectModel(filtered[highlighted].name);
      } else if (open && query.trim()) {
        // Allow custom value on Enter
        selectModel(query.trim());
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      setQuery("");
    }
  };

  const showDropdown = open && !disabled;
  const hasModels = models.length > 0;

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Trigger: shows the current value, or a placeholder */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none transition"
        style={{
          borderColor: "var(--border)",
          background: "var(--surface)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
        }}
      >
        <span
          className={value ? "text-[var(--ink)]" : "text-[var(--ink-3)]"}
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {loading ? "Loading…" : value || placeholder}
        </span>
        <ChevronDown
          className="h-4 w-4 shrink-0 text-[var(--ink-3)]"
          style={{ transform: showDropdown ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}
        />
      </button>

      {/* Dropdown */}
      {showDropdown && (
        <div
          className="absolute z-50 mt-1 w-full overflow-hidden rounded-[5px] border shadow-lg"
          style={{
            background: "var(--white)",
            borderColor: "var(--border)",
          }}
        >
          {/* Search input */}
          <div
            className="flex items-center gap-2 border-b px-3 py-2"
            style={{ borderColor: "var(--border)" }}
          >
            <Search className="h-3.5 w-3.5 shrink-0 text-[var(--ink-3)]" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setHighlighted(0);
                // Live-update the value as the user types (for custom model names)
                onChange(e.target.value);
              }}
              onKeyDown={handleKeyDown}
              placeholder="Search or type…"
              className="w-full bg-transparent text-[13px] text-[var(--ink)] outline-none"
              aria-controls={listId}
              aria-autocomplete="list"
            />
          </div>

          {/* Model list */}
          <div
            id={listId}
            className="max-h-[200px] overflow-y-auto"
            role="listbox"
          >
            {filtered.length === 0 && !hasModels && (
              <div className="px-3 py-3 text-[12px] text-[var(--ink-3)]">
                No models discovered. Type a model name above and press Enter.
              </div>
            )}
            {filtered.length === 0 && hasModels && (
              <div className="px-3 py-3 text-[12px] text-[var(--ink-3)]">
                No matches. Press Enter to use "{query}" as a custom model.
              </div>
            )}
            {filtered.map((m, i) => (
              <button
                key={m.id}
                type="button"
                role="option"
                aria-selected={m.name === value}
                onClick={() => selectModel(m.name)}
                onMouseEnter={() => setHighlighted(i)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] transition"
                style={{
                  background:
                    i === highlighted ? "var(--surface)" : "transparent",
                  color: "var(--ink)",
                  cursor: "pointer",
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {m.name}
                </span>
                {m.name === value && (
                  <Check className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                )}
              </button>
            ))}
          </div>

          {/* Footer hint */}
          {hasModels && (
            <div
              className="border-t px-3 py-1.5 text-[11px] text-[var(--ink-3)]"
              style={{ borderColor: "var(--border)" }}
            >
              {filtered.length} of {models.length} models
            </div>
          )}
        </div>
      )}
    </div>
  );
}
