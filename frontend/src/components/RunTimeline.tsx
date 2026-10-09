import { useEffect, useMemo, useRef, useState } from "react";
import type { RunDetail, TimelineEvent } from "@/lib/types";
import { buildTraceLayout } from "@/lib/traceLayout";
import type { TraceRow } from "@/lib/traceLayout";
import { ENVELOPE_TYPES, spanSearchText } from "@/lib/traceFormat";
import { TraceWaterfall } from "./TraceWaterfall";
import { TraceInspector } from "./TraceInspector";

interface Props {
  events: TimelineEvent[];
  run?: RunDetail;
  providerNames?: Record<string, string>;
  onViewMessages?: () => void;
}

/** Trace workspace: aligned span tree + waterfall on the left, sticky
 * inspector on the right. Timing comes from the frozen buildTraceLayout —
 * parent links are exact call/subagent pairs, never temporal guesses. */
export function RunTimeline({ events, run, providerNames = {}, onViewMessages }: Props) {
  const layout = useMemo(() => buildTraceLayout(events, run), [events, run]);
  const [showEvents, setShowEvents] = useState(false);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const defaultSelect = useMemo(() => {
    const first =
      layout.rows.find((r) => r.event?.type === "model_call") ??
      layout.rows.find((r) => r.event?.type === "tool_call");
    return first?.id ?? layout.rootId;
  }, [layout]);
  const [selectedId, setSelectedId] = useState(defaultSelect);
  const rawSelected = layout.byId.has(selectedId) ? selectedId : defaultSelect;

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const keep = new Set<string>();
    for (const row of layout.rows) {
      if (row.event === null) continue;
      if (!showEvents && ENVELOPE_TYPES.has(row.event.type)) continue;
      if (!q || spanSearchText(row, providerNames).includes(q)) {
        // matching row + every ancestor survives the filter
        let cur: string | null = row.id;
        while (cur && !keep.has(cur)) {
          keep.add(cur);
          cur = layout.byId.get(cur)?.parentId ?? null;
        }
      }
    }
    const out: TraceRow[] = [];
    for (const row of layout.rows) {
      if (row.event === null) {
        out.push(row);
        continue;
      }
      if (!keep.has(row.id)) continue;
      // hide descendants of collapsed nodes — but an active search
      // temporarily ignores collapse so matching children surface.
      if (q === "") {
        let hidden = false;
        let anc: string | null = row.parentId;
        while (anc) {
          if (collapsed.has(anc)) {
            hidden = true;
            break;
          }
          anc = layout.byId.get(anc)?.parentId ?? null;
        }
        if (hidden) continue;
      }
      out.push(row);
    }
    return out;
  }, [layout, showEvents, search, collapsed, providerNames]);

  const effectiveSelected = useMemo(() => {
    // never let the inspector show a row hidden by search or collapse —
    // prefer the first visible span, else the root envelope
    if (visible.some((r) => r.id === rawSelected)) return rawSelected;
    return visible.find((r) => r.event !== null)?.id ?? layout.rootId;
  }, [visible, rawSelected, layout.rootId]);
  const selected = layout.byId.get(effectiveSelected) ?? layout.byId.get(layout.rootId)!;

  const treeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    document.getElementById(`evt-${effectiveSelected}`)?.scrollIntoView({ block: "nearest" });
  }, [effectiveSelected]);

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const revealRow = (id: string) => {
    // open every collapsed ancestor so the target is actually visible
    setCollapsed((prev) => {
      const next = new Set(prev);
      let anc = layout.byId.get(id)?.parentId ?? null;
      while (anc) {
        next.delete(anc);
        anc = layout.byId.get(anc)?.parentId ?? null;
      }
      return next;
    });
    setSelectedId(id);
  };

  const jumpParent = (row: TraceRow) => {
    const parent = row.event?.parent_id;
    if (!parent || !layout.byId.has(parent)) return;
    revealRow(parent);
    requestAnimationFrame(() => {
      document.getElementById(`evt-${parent}`)?.scrollIntoView({ block: "nearest" });
    });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    // nested interactive controls own their keys — don't double-fire
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "BUTTON" || tag === "INPUT" || tag === "A") return;
    const idx = visible.findIndex((r) => r.id === effectiveSelected);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = visible[Math.min(idx + 1, visible.length - 1)];
      if (next) setSelectedId(next.id);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = visible[Math.max(idx - 1, 0)];
      if (prev) setSelectedId(prev.id);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      if (collapsed.has(effectiveSelected)) toggle(effectiveSelected);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      // root can collapse too — the guard only needs children
      if (!collapsed.has(effectiveSelected) && selected.children.length) {
        toggle(effectiveSelected);
      } else if (selected.parentId) {
        revealRow(selected.parentId);
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selected.children.length) toggle(selected.id);
    }
  };

  const observed = layout.rows.filter((r) => r.event !== null && !ENVELOPE_TYPES.has(r.event.type)).length;

  if (events.length === 0) {
    return (
      <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">
        No trace events recorded for this run — the model and tools it used
        didn't emit observable spans.
      </p>
    );
  }

  return (
    <div className="rounded-[8px] border" style={{ borderColor: "var(--border)", background: "var(--white)" }}>
      {/* Toolbar */}
      <div
        className="flex flex-wrap items-center gap-2 border-b px-2.5 py-1.5"
        style={{ borderColor: "var(--border)" }}
      >
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search spans — name, capability, provider, model, status"
          className="w-64 max-w-full rounded-[4px] px-2 py-1 text-[11px] text-[var(--ink)]"
          style={{ border: "1px solid var(--border)", background: "var(--white)" }}
          aria-label="Search trace spans"
        />
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--ink-2)]">
          <input
            type="checkbox"
            checked={showEvents}
            onChange={(e) => setShowEvents(e.target.checked)}
          />
          Show events
        </label>
        <span className="ml-auto text-[10px] text-[var(--ink-3)]">
          {observed} observation{observed === 1 ? "" : "s"} recorded
        </span>
      </div>

      {/* Split: tree+waterfall | inspector */}
      <div className="flex flex-col lg:flex-row">
        <div className="min-w-0 flex-1 overflow-x-auto lg:w-2/3">
          <TraceWaterfall
            rows={visible}
            collapsed={collapsed}
            selectedId={effectiveSelected}
            providerNames={providerNames}
            extentMs={layout.extentMs}
            onSelect={(id) => {
              setSelectedId(id);
              treeRef.current?.focus({ preventScroll: true });
            }}
            onToggle={toggle}
            onJumpParent={jumpParent}
            onKeyDown={onKeyDown}
            containerRef={treeRef}
          />
          {visible.every((r) => r.event === null) && (
            <p className="px-3 py-4 text-[11px] italic text-[var(--ink-3)]">
              No matching observations.
            </p>
          )}
        </div>
        <div
          className="w-full shrink-0 border-t lg:sticky lg:top-0 lg:w-1/3 lg:border-l lg:border-t-0"
          style={{ borderColor: "var(--border)" }}
        >
          <TraceInspector
            row={selected}
            run={run}
            providerNames={providerNames}
            onViewMessages={onViewMessages}
          />
        </div>
      </div>
      <p className="border-t px-2.5 py-1.5 text-[10px] text-[var(--ink-3)]" style={{ borderColor: "var(--border)" }}>
        Span bars show recorded or latency-derived placement; per-call request/response bodies are not captured.
        Unlinked legacy records may describe the same call — they are not merged.
      </p>
    </div>
  );
}
