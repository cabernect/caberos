import { ChevronDown, ChevronRight, CornerDownRight } from "lucide-react";
import type { TraceRow } from "@/lib/traceLayout";
import { fmtMs, spanHue, spanLabel, timingLabel } from "@/lib/traceFormat";

export const LABEL_CELL =
  "w-[200px] sm:w-[240px] xl:w-[260px] shrink-0";
export const DURATION_CELL = "w-[64px] shrink-0";

interface Props {
  rows: TraceRow[]; // visible rows only, root first
  collapsed: Set<string>;
  selectedId: string;
  providerNames: Record<string, string>;
  extentMs: number;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
  onJumpParent: (row: TraceRow) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

/** Dense aligned tree + duration bars — one row per span. The header's
 * label/track/duration cells use the exact same widths as the rows so
 * the ruler ticks sit over the bar geometry. */
export function TraceWaterfall({
  rows,
  collapsed,
  selectedId,
  providerNames,
  extentMs,
  onSelect,
  onToggle,
  onJumpParent,
  onKeyDown,
  containerRef,
}: Props) {
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    at: `${f * 100}%`,
    label: fmtMs(extentMs * f),
  }));

  return (
    <div
      ref={containerRef}
      role="tree"
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-activedescendant={`evt-${selectedId}`}
      className="min-w-[464px] outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)]"
      aria-label="Run trace spans"
    >
      {/* Ruler — label/track/duration cells match row geometry exactly */}
      <div className="flex items-stretch border-b" style={{ borderColor: "var(--border)" }}>
        <div className={`${LABEL_CELL} px-2 py-1 text-[9px] uppercase tracking-wide text-[var(--ink-3)]`} />
        <div className="relative h-4 flex-1 min-w-[200px]" data-testid="ruler-track">
          {ticks.map((t, i) => (
            <span
              key={i}
              className="absolute text-[9px] text-[var(--ink-3)]"
              style={{
                left: t.at,
                transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)",
              }}
            >
              {t.label}
            </span>
          ))}
        </div>
        <div className={`${DURATION_CELL}`} />
      </div>

      {rows.map((row) => {
        const isRoot = row.event === null;
        const event = row.event;
        const isSelected = row.id === selectedId;
        const hasChildren = row.children.length > 0;
        const isCollapsed = collapsed.has(row.id);
        const unpositioned = row.leftPercent === null;
        const unlinked = event?.type === "tool_call" && event.call_id === null;
        return (
          <div
            key={row.id}
            id={`evt-${row.id}`}
            role="treeitem"
            aria-selected={isSelected}
            aria-level={row.depth + 1}
            aria-expanded={hasChildren ? !isCollapsed : undefined}
            tabIndex={-1}
            onClick={() => onSelect(row.id)}
            className="flex cursor-pointer items-stretch border-b"
            style={{
              borderColor: "var(--border-soft)",
              background: isSelected ? "var(--accent-bg, rgba(107,109,63,0.10))" : "transparent",
            }}
            data-testid={`trace-row-${row.id}`}
          >
            {/* Label column */}
            <div className={`flex ${LABEL_CELL} min-w-0 items-center gap-1 truncate px-1 py-1`}>
              <span style={{ width: row.depth * 14, flexShrink: 0 }} />
              {hasChildren ? (
                <button
                  type="button"
                  aria-label={isCollapsed ? "Expand" : "Collapse"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggle(row.id);
                  }}
                  className="flex h-4 w-4 shrink-0 items-center justify-center"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-3)", padding: 0 }}
                >
                  {isCollapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>
              ) : (
                <span className="w-4 shrink-0" />
              )}
              <span
                className="truncate text-[11px]"
                style={{
                  color: isRoot ? "var(--ink)" : "var(--ink-2)",
                  fontWeight: isRoot ? 600 : 400,
                  fontFamily: event?.type === "tool_call" ? "monospace" : undefined,
                }}
                title={spanLabel(row, providerNames)}
              >
                {spanLabel(row, providerNames)}
              </span>
              {unlinked && (
                <span
                  className="shrink-0 rounded-[3px] border border-dashed px-1 text-[9px]"
                  style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
                  title="No call correlation recorded"
                >
                  unlinked
                </span>
              )}
              {event?.sub_agent_id && (
                <span
                  className="shrink-0 rounded-[3px] px-1 text-[9px]"
                  style={{ background: "var(--surface)", color: "var(--ink-3)", border: "1px solid var(--border)" }}
                >
                  sub {event.sub_agent_id.slice(0, 6)}
                </span>
              )}
              {event?.parent_id && (
                <button
                  type="button"
                  aria-label={`Jump to parent event ${event.parent_id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onJumpParent(row);
                  }}
                  className="shrink-0"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--accent)", padding: 0 }}
                >
                  <CornerDownRight className="h-3 w-3" />
                </button>
              )}
            </div>

            {/* Waterfall column */}
            <div className="relative flex-1 min-w-[200px]" data-testid="trace-bar-track">
              {unpositioned ? (
                <span
                  className="mx-1 inline-block rounded-[3px] border border-dashed px-1 text-[9px] italic text-[var(--ink-3)]"
                  style={{ borderColor: "var(--border)" }}
                >
                  Unknown time
                </span>
              ) : (
                <>
                  {[0.25, 0.5, 0.75].map((f) => (
                    <span
                      key={f}
                      className="absolute top-0 bottom-0"
                      style={{ left: `${f * 100}%`, borderLeft: "1px solid var(--border-soft)" }}
                    />
                  ))}
                  {row.widthPercent !== null && row.widthPercent > 0 ? (
                    <span
                      data-testid={`trace-span-bar-${row.id}`}
                      className="absolute top-1 h-3 rounded-[2px]"
                      style={{
                        left: `${row.leftPercent}%`,
                        width: `max(${row.widthPercent}%, 4px)`,
                        background: isRoot ? "var(--ink, #44403c)" : spanHue(event!.type),
                        opacity: row.adjusted ? 0.55 : 0.85,
                      }}
                      title={`${fmtMs(row.durationMs ?? 0)} (${timingLabel(row)})`}
                    />
                  ) : (
                    <span
                      data-testid={`trace-span-bar-${row.id}`}
                      className="absolute top-1 h-3 w-[5px] rounded-[2px]"
                      style={{
                        left: `${row.leftPercent}%`,
                        border: "1.5px solid",
                        borderColor: isRoot ? "var(--ink, #44403c)" : spanHue(event!.type),
                      }}
                      title={row.durationMs === 0 ? "0ms" : "instant"}
                    />
                  )}
                </>
              )}
            </div>

            {/* Duration column */}
            <div className={`${DURATION_CELL} px-1 py-1 text-right text-[10px] tabular-nums text-[var(--ink-3)]`}>
              {row.durationMs !== null ? fmtMs(row.durationMs) : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
