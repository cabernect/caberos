import { useState } from "react";

interface DiffBlockProps {
  diff: string;
  path: string;
  action: "created" | "modified" | "unchanged";
}

export function DiffBlock({ diff, path, action }: DiffBlockProps) {
  const [expanded, setExpanded] = useState(true);

  if (action === "unchanged") {
    return (
      <div className="mb-2 rounded-[5px] px-2.5 py-1.5 font-mono text-[11px]"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink-3)" }}
      >
        No changes — file content identical
      </div>
    );
  }

  if (action === "created" || !diff) {
    return (
      <div className="mb-2 rounded-[5px] px-2.5 py-1.5 font-mono text-[11px]"
        style={{ background: "var(--surface)", border: "1px solid var(--success)", color: "var(--ink-2)" }}
      >
        ✓ New file created: {path}
      </div>
    );
  }

  const lines = diff.split("\n");
  const addedCount = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length;
  const removedCount = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;

  return (
    <div className="mb-2 rounded-[5px] border overflow-hidden"
      style={{ borderColor: "var(--border)" }}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-2.5 py-1.5 text-left transition"
        style={{ background: "var(--surface)", cursor: "pointer" }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--white)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "var(--surface)"; }}
      >
        <span className="font-mono text-[11px]" style={{ color: "var(--ink-2)" }}>
          {expanded ? "▼" : "▶"} diff — {path}
        </span>
        <span className="flex gap-2 font-mono text-[10px]">
          <span style={{ color: "var(--success)" }}>+{addedCount}</span>
          <span style={{ color: "var(--danger)" }}>-{removedCount}</span>
        </span>
      </button>

      {/* Diff body */}
      {expanded && (
        <div className="overflow-x-auto font-mono text-[11px] leading-[1.5]"
          style={{ background: "var(--white)" }}
        >
          {lines.map((line, i) => {
            // Skip file headers (--- / +++) — show them muted
            if (line.startsWith("---") || line.startsWith("+++")) {
              return (
                <div key={i} className="px-2.5"
                  style={{ color: "var(--ink-3)", background: "var(--surface)" }}
                >
                  {line}
                </div>
              );
            }
            // Hunk header (@@)
            if (line.startsWith("@@")) {
              return (
                <div key={i} className="px-2.5 py-0.5"
                  style={{ color: "var(--info, var(--accent))", background: "var(--surface)" }}
                >
                  {line}
                </div>
              );
            }
            // Added line
            if (line.startsWith("+")) {
              return (
                <div key={i} className="px-2.5"
                  style={{ background: "rgba(34, 197, 94, 0.18)", color: "var(--ink)" }}
                >
                  <span style={{ color: "var(--success)" }}>+</span>
                  {line.slice(1)}
                </div>
              );
            }
            // Removed line
            if (line.startsWith("-")) {
              return (
                <div key={i} className="px-2.5"
                  style={{ background: "rgba(239, 68, 68, 0.18)", color: "var(--ink)" }}
                >
                  <span style={{ color: "var(--danger)" }}>-</span>
                  {line.slice(1)}
                </div>
              );
            }
            // Context line
            return (
              <div key={i} className="px-2.5"
                style={{ color: "var(--ink-3)" }}
              >
                <span> </span>{line}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
