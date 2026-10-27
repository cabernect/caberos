import { ChevronDown, ChevronRight, CornerDownRight } from "lucide-react";
import type { TraceRow } from "@/lib/traceLayout";
import { fmtMs, spanHue, spanLabel, timingLabel } from "@/lib/traceFormat";

export const LABEL_CELL =
  "w-[200px] sm:w-[240px] xl:w-[260px] shrink-0";
export const DURATION_CELL = "w-[64px] shrink-0";

interface Props {
  rows: TraceRow[]; // visible rows only, root first
  rootId: string;
  collapsed: Set<string>;
  expandedGroups: Set<string>;
  slowIds: Set<string>;
  selectedId: string;
  providerNames: Record<string, string>;
  extentMs: number;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
  onToggleGroup: (id: string) => void;
  onJumpParent: (row: TraceRow) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

/** Aligned span rows — mono labels, each bar a colored fill on a full-width
 * track pill so duration reads against the whole run extent. Rows render
 * flat (one indent level removed); the Run root row stays as the envelope
 * + run-inspector entry point. */
export function TraceWaterfall({
  rows,
  rootId,
  collapsed,
  expandedGroups,
  slowIds,
  selectedId,
  providerNames,
  extentMs,
  onSelect,
  onToggle,
  onToggleGroup,
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
        <div className={`${LABEL_CELL} px-3 py-1.5 text-[9px] uppercase tracking-wide text-[var(--ink-3)]`} />
        <div className="h-5 flex-1 min-w-[200px] px-1" data-testid="ruler-track">
          <div className="relative h-full">
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
        </div>
        <div className={`${DURATION_CELL}`} />
      </div>

      {rows.map((row) => {
        const isRoot = row.id === rootId;
        const event = row.event;
        const isSelected = row.id === selectedId;
        const isGroup = !!row.group;
        const hasChildren = row.children.length > 0 || isGroup;
        const isCollapsed = isGroup ? !expandedGroups.has(row.id) : collapsed.has(row.id);
        const unpositioned = row.leftPercent === null;
        const durationOnly = unpositioned && row.durationMs !== null;
        const unlinked = event?.type === "tool_call" && event.call_id === null;
        const slow = slowIds.has(row.id) || !!row.group?.some((m) => slowIds.has(m.id));
        const barColor = isRoot ? "var(--ink, #44403c)" : slow ? "var(--warning)" : spanHue(event?.type ?? "tool_call");
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
            className="flex cursor-pointer items-center border-b transition-colors"
            style={{
              borderColor: "var(--border-soft)",
              background: isSelected ? "var(--accent-bg, rgba(107,109,63,0.10))" : "transparent",
            }}
            data-testid={`trace-row-${row.id}`}
          >
            {/* Label column */}
            <div className={`flex ${LABEL_CELL} min-w-0 items-center gap-1 truncate px-3 py-2`}>
              <span style={{ width: Math.max(0, row.depth - 1) * 14, flexShrink: 0 }} />
              {hasChildren ? (
                <button
                  type="button"
                  aria-label={isCollapsed ? "Expand" : "Collapse"}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isGroup) onToggleGroup(row.id);
                    else onToggle(row.id);
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
                className="truncate text-[12px]"
                style={{
                  color: isRoot ? "var(--ink)" : "var(--ink-2)",
                  fontWeight: isRoot ? 600 : 400,
                  fontFamily: event?.type === "tool_call" || isGroup ? "monospace" : undefined,
                }}
                title={isGroup ? row.groupLabel : spanLabel(row, providerNames)}
              >
                {isGroup ? row.groupLabel : spanLabel(row, providerNames)}
              </span>
              {isGroup && (
                <span
                  className="shrink-0 rounded-full bg-sunken px-1.5 py-px text-[9px] font-medium text-ink-muted"
                  title={`${row.group!.length} repeated calls — expand to inspect each`}
                >
                  ×{row.group!.length}
                </span>
              )}
              {row.postRun && (
                <span
                  className="shrink-0 rounded-full bg-sunken px-1.5 py-px text-[9px] font-medium text-ink-muted"
                  title={`${row.postRunCount ?? row.children.length} maintenance records ledgered after the run ended`}
                >
                  ×{row.postRunCount ?? row.children.length}
                </span>
              )}
              {unlinked && (
                <span
                  className="shrink-0 rounded-[3px] border border-dashed px-1 text-[9px]"
                  style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
                  title="No call correlation recorded"
                >
                  unlinked
                </span>
              )}
              {row.outsideWindow && (
                <span
                  className="shrink-0 rounded-[3px] px-1 text-[9px]"
                  style={{ background: "var(--ground)", color: "var(--ink-3)" }}
                  title="Recorded after the run's recorded window — session maintenance ledgered to this run"
                >
                  post-run
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
              {event?.parent_id && !isGroup && (
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

            {/* Waterfall column — colored fill on a full-width track pill.
             * Bars position inside the track so % aligns with its edges. */}
            <div className="flex-1 min-w-[200px] self-center px-1" data-testid="trace-bar-track">
              <div
                className="relative h-2.5 w-full rounded-full"
                style={{ background: "var(--track)" }}
              >
                {durationOnly ? (
                  <span
                    data-testid={`trace-span-bar-${row.id}`}
                    className="absolute top-0 h-full rounded-full"
                    style={{
                      left: 0,
                      width: `max(${(row.durationMs! / Math.max(extentMs, 1)) * 100}%, 4px)`,
                      background: barColor,
                      opacity: 0.55,
                    }}
                    title={
                      row.outsideWindow
                        ? `${fmtMs(row.durationMs!)} — ledgered after the run ended; bar shows duration only`
                        : `${fmtMs(row.durationMs!)} — start not recorded, bar shows duration only`
                    }
                  />
                ) : unpositioned ? (
                  <span
                    className="absolute left-0 top-1/2 -translate-y-1/2 rounded-[3px] border border-dashed px-1 text-[9px] italic text-[var(--ink-3)]"
                    style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                  >
                    {row.postRun ? "ledgered after run end" : row.outsideWindow ? "after run end" : "Unknown time"}
                  </span>
                ) : row.widthPercent !== null && row.widthPercent > 0 ? (
                  <span
                    data-testid={`trace-span-bar-${row.id}`}
                    className="absolute top-0 h-full rounded-full"
                    style={{
                      left: `${row.leftPercent}%`,
                      width: `max(${row.widthPercent}%, 4px)`,
                      background: barColor,
                      opacity: row.adjusted ? 0.55 : 0.85,
                    }}
                    title={`${fmtMs(row.durationMs ?? 0)} (${timingLabel(row)})`}
                  />
                ) : (
                  <span
                    data-testid={`trace-span-bar-${row.id}`}
                    className="absolute top-0 h-full w-[5px] rounded-full"
                    style={{
                      left: `${row.leftPercent}%`,
                      border: "1.5px solid",
                      borderColor: barColor,
                      background: "var(--surface)",
                    }}
                    title={row.durationMs === 0 ? "0ms" : "instant"}
                  />
                )}
              </div>
            </div>

            {/* Duration column */}
            <div className={`${DURATION_CELL} px-3 py-2 text-right text-[11px] tabular-nums text-[var(--ink-3)]`}>
              {row.durationMs !== null ? fmtMs(row.durationMs) : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
