import { useEffect, useMemo, useRef, useState } from "react";
import { Info, Search } from "lucide-react";
import type { RunDetail, TimelineEvent } from "@/lib/types";
import { buildTraceLayout } from "@/lib/traceLayout";
import type { TraceRow } from "@/lib/traceLayout";
import { ENVELOPE_TYPES, spanSearchText } from "@/lib/traceFormat";
import { Toggle } from "@/components/ui/toggle";
import { TraceWaterfall } from "./TraceWaterfall";
import { TraceInspector } from "./TraceInspector";

interface Props {
  events: TimelineEvent[];
  run?: RunDetail;
  providerNames?: Record<string, string>;
  onViewMessages?: () => void;
}

const ROW_CAP = 15;

/** Coarse identity used for grouping and the count chips — capability name
 * for tool calls, "generation" for model calls, event type otherwise. */
function rowGroupKey(row: TraceRow): string | null {
  const e = row.event;
  if (!e) return null;
  if (e.type === "model_call") return "generation";
  if (e.type === "tool_call") return String(e.data.capability ?? e.type);
  return e.type;
}

/** Trace workspace: aligned span tree + waterfall on the left, sticky
 * inspector on the right. Timing comes from the frozen buildTraceLayout —
 * parent links are exact call/subagent pairs, never temporal guesses. */
export function RunTimeline({ events, run, providerNames = {}, onViewMessages }: Props) {
  const layout = useMemo(() => buildTraceLayout(events, run), [events, run]);
  const [showEvents, setShowEvents] = useState(false);
  const [groupRepeats, setGroupRepeats] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [search, setSearch] = useState("");
  const [userCollapsed, setUserCollapsed] = useState<Set<string>>(new Set());
  // Post-run housekeeping starts collapsed — the waterfall leads with the
  // run's own work; one click on the section reveals the ledgered records.
  const [expandedPostRun, setExpandedPostRun] = useState(false);
  const postRunRow = useMemo(() => layout.rows.find((r) => r.postRun), [layout]);
  const collapsed = useMemo(() => {
    const s = new Set(userCollapsed);
    if (postRunRow && !expandedPostRun) s.add(postRunRow.id);
    return s;
  }, [userCollapsed, expandedPostRun, postRunRow]);

  const defaultSelect = useMemo(() => {
    const first =
      layout.rows.find((r) => r.event?.type === "model_call") ??
      layout.rows.find((r) => r.event?.type === "tool_call");
    return first?.id ?? layout.rootId;
  }, [layout]);
  const [selectedId, setSelectedId] = useState(defaultSelect);
  const rawSelected = layout.byId.has(selectedId) || selectedId.startsWith("grp:")
    ? selectedId
    : defaultSelect;

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
        // Section rows only render while at least one member survives the
        // filter — no dangling "post-run" header on an unrelated search.
        if (!row.postRun || row.children.some((cid) => keep.has(cid))) {
          out.push(row);
        }
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

  // Fold same-name sibling leaves into "name ×N" rows when grouping is on.
  // Grouped by (parent, key) across the whole sibling list — order follows
  // each group's first occurrence; expanding a group reveals members in
  // place, one level deeper.
  const grouped = useMemo(() => {
    if (!groupRepeats || search.trim() !== "") return visible;
    const out: TraceRow[] = [];
    const slots = new Map<string, number>();
    const buckets = new Map<string, TraceRow[]>();
    for (const row of visible) {
      const key =
        row.event && !ENVELOPE_TYPES.has(row.event.type) && row.children.length === 0 && !row.outsideWindow
          ? rowGroupKey(row)
          : null;
      if (!key) {
        out.push(row);
        continue;
      }
      const gid = `${row.parentId ?? "root"}|${key}`;
      if (!buckets.has(gid)) {
        buckets.set(gid, []);
        slots.set(gid, out.length);
        out.push(row); // placeholder, replaced below
      }
      buckets.get(gid)!.push(row);
    }
    // Descending slot order — an expanded group inserts extra rows, and
    // splicing high-to-low keeps the earlier slots valid.
    const ordered = [...buckets.entries()].sort(
      (a, b) => slots.get(b[0])! - slots.get(a[0])!,
    );
    for (const [gid, members] of ordered) {
      if (members.length < 2) continue; // lone row — already in place
      const lefts = members.map((m) => m.leftPercent).filter((v): v is number => v !== null);
      const rights = members.map((m) => (m.leftPercent ?? 0) + (m.widthPercent ?? 0));
      const groupRow: TraceRow = {
        ...members[0],
        id: `grp:${gid}`,
        children: [],
        group: members,
        groupKey: gid,
        groupLabel: members[0].event?.type === "model_call" ? "generation" : (rowGroupKey(members[0]) ?? ""),
        durationMs: members.every((m) => m.durationMs !== null)
          ? members.reduce((a, m) => a + (m.durationMs ?? 0), 0)
          : members[0].durationMs,
        leftPercent: lefts.length ? Math.min(...lefts) : null,
        widthPercent: lefts.length ? Math.max(...rights) - Math.min(...lefts) : null,
      };
      const insert: TraceRow[] = [groupRow];
      if (expandedGroups.has(groupRow.id)) {
        insert.push(...members.map((m) => ({ ...m, depth: m.depth + 1 })));
      }
      out.splice(slots.get(gid)!, 1, ...insert);
    }
    return out;
  }, [visible, groupRepeats, expandedGroups, search]);

  // Top-decile durations get the warning color — the mockup's slowest bars.
  const slowIds = useMemo(() => {
    const durations = visible
      .filter((r) => r.event !== null && r.durationMs !== null)
      .map((r) => r.durationMs!)
      .sort((a, b) => b - a);
    if (durations.length < 3) return new Set<string>();
    const cutoff = durations[Math.floor((durations.length - 1) * 0.1)];
    if (cutoff <= 0) return new Set<string>();
    return new Set(
      visible.filter((r) => r.durationMs !== null && r.durationMs >= cutoff).map((r) => r.id),
    );
  }, [visible]);

  const q = search.trim().toLowerCase();
  const truncated = q === "" && !showAll && grouped.length > ROW_CAP;
  const renderRows = truncated ? grouped.slice(0, ROW_CAP) : grouped;

  const effectiveSelected = useMemo(() => {
    // never let the inspector show a row hidden by search or collapse —
    // prefer the first visible span, else the root envelope
    if (grouped.some((r) => r.id === rawSelected)) return rawSelected;
    return grouped.find((r) => r.event !== null)?.id ?? layout.rootId;
  }, [grouped, rawSelected, layout.rootId]);
  const selected =
    grouped.find((r) => r.id === effectiveSelected) ??
    layout.byId.get(layout.rootId)!;

  const treeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    document.getElementById(`evt-${effectiveSelected}`)?.scrollIntoView({ block: "nearest" });
  }, [effectiveSelected]);

  const toggle = (id: string) => {
    if (layout.byId.get(id)?.postRun) {
      setExpandedPostRun((v) => !v);
      return;
    }
    setUserCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleGroup = (id: string) =>
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const revealRow = (id: string) => {
    // open every collapsed ancestor so the target is actually visible —
    // including the post-run section, which lives outside userCollapsed
    const toOpen: string[] = [];
    let inPostRun = false;
    let anc = layout.byId.get(id)?.parentId ?? null;
    while (anc) {
      const a = layout.byId.get(anc);
      if (a?.postRun) inPostRun = true;
      else toOpen.push(anc);
      anc = a?.parentId ?? null;
    }
    if (inPostRun) setExpandedPostRun(true);
    if (toOpen.length > 0) {
      setUserCollapsed((prev) => {
        const next = new Set(prev);
        for (const openId of toOpen) next.delete(openId);
        return next;
      });
    }
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
    const idx = renderRows.findIndex((r) => r.id === effectiveSelected);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = renderRows[Math.min(idx + 1, renderRows.length - 1)];
      if (next) setSelectedId(next.id);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = renderRows[Math.max(idx - 1, 0)];
      if (prev) setSelectedId(prev.id);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      if (selected.group) toggleGroup(selected.id);
      else if (collapsed.has(effectiveSelected)) toggle(effectiveSelected);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      if (selected.group && expandedGroups.has(selected.id)) {
        toggleGroup(selected.id);
      } else if (!collapsed.has(effectiveSelected) && selected.children.length) {
        toggle(effectiveSelected);
      } else if (selected.parentId) {
        revealRow(selected.parentId);
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selected.group) toggleGroup(selected.id);
      else if (selected.children.length) toggle(selected.id);
    }
  };

  const observed = layout.rows.filter((r) => r.event !== null && !ENVELOPE_TYPES.has(r.event.type)).length;
  const durationOnlyCount = visible.filter(
    (r) => r.event !== null && r.leftPercent === null && r.durationMs !== null,
  ).length;

  // Count chips — one per call kind across all non-envelope observations.
  const callCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of layout.rows) {
      if (row.event === null || ENVELOPE_TYPES.has(row.event.type)) continue;
      const key = rowGroupKey(row);
      if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [layout]);

  if (events.length === 0) {
    return (
      <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">
        No trace events recorded for this run — the model and tools it used
        didn't emit observable spans.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
      {/* Observations list — its own card, separate from the inspector */}
      <div
        className="min-w-0 flex-1 rounded-lg border lg:w-2/3"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        {/* Toolbar */}
        <div
          className="flex flex-wrap items-center gap-2 border-b px-3 py-2"
          style={{ borderColor: "var(--border)" }}
        >
          <span className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-faint" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search spans"
              className="w-56 max-w-full rounded-md border border-line bg-ground py-1 pl-7 pr-2 text-[12px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
              aria-label="Search trace spans"
            />
          </span>
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--ink-2)]">
          <input
            type="checkbox"
            checked={showEvents}
            onChange={(e) => setShowEvents(e.target.checked)}
          />
          Show events
        </label>
        <span className="flex items-center gap-1.5 text-[11px] text-[var(--ink-2)]">
          <Toggle
            size="sm"
            checked={groupRepeats}
            onCheckedChange={setGroupRepeats}
            aria-label="Group repeated calls"
          />
          Group repeated calls
        </span>
        <span className="ml-auto text-[10px] text-[var(--ink-3)]">
          {observed} observation{observed === 1 ? "" : "s"} recorded
        </span>
      </div>

      {/* Call-count chips — click filters the span list */}
      {callCounts.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-1.5 border-b px-2.5 py-1.5"
          style={{ borderColor: "var(--border)" }}
        >
          {callCounts.map(([key, n]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSearch(key === "generation" ? "generation" : key)}
              className="cursor-pointer rounded-full px-2 py-0.5 font-mono text-[10px] transition-colors"
              style={{
                border: "1px solid var(--border)",
                background: search === key ? "var(--accent-bg, rgba(107,109,63,0.10))" : "var(--surface)",
                color: "var(--ink-2)",
              }}
              title={`Filter spans to ${key}`}
            >
              {key} ×{n}
            </button>
          ))}
        </div>
      )}

      {/* Duration-only note */}
      {durationOnlyCount > 0 && (
        <p
          className="flex items-center gap-1.5 border-b px-2.5 py-1.5 text-[10px] text-[var(--ink-3)]"
          style={{ borderColor: "var(--border)" }}
        >
          <Info className="h-3 w-3 shrink-0" />
          Start times weren't recorded for {durationOnlyCount} step
          {durationOnlyCount === 1 ? "" : "s"}, so those bars show each step's
          duration only. Some may have run in parallel.
        </p>
      )}

      {/* Waterfall */}
      <div className="overflow-x-auto">
        <TraceWaterfall
          rows={renderRows}
          rootId={layout.rootId}
          collapsed={collapsed}
          expandedGroups={expandedGroups}
          slowIds={slowIds}
          selectedId={effectiveSelected}
          providerNames={providerNames}
          extentMs={layout.extentMs}
          onSelect={(id) => {
            setSelectedId(id);
            treeRef.current?.focus({ preventScroll: true });
          }}
          onToggle={toggle}
          onToggleGroup={toggleGroup}
          onJumpParent={jumpParent}
          onKeyDown={onKeyDown}
          containerRef={treeRef}
        />
        {renderRows.every((r) => r.event === null) && (
          <p className="px-3 py-4 text-[11px] italic text-[var(--ink-3)]">
            No matching observations.
          </p>
        )}
      </div>
      {truncated && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="block w-full cursor-pointer border-t px-3 py-2 text-left text-[12px] font-medium text-accent hover:bg-sunken"
          style={{ borderColor: "var(--border-soft)" }}
        >
          + {grouped.length - ROW_CAP} more observations
        </button>
      )}
      <p className="border-t px-3 py-1.5 text-[10px] text-[var(--ink-3)]" style={{ borderColor: "var(--border)" }}>
        Span bars show recorded or latency-derived placement inside the run window; post-run maintenance ledgered to the run shows duration only. Request inputs are available when captured and retained; response bodies are not recorded. Unlinked legacy records may describe the same call — they are not merged.
      </p>
      </div>

      {/* Inspector — a separate card to the right, sticky on wide screens */}
      <div className="w-full shrink-0 lg:sticky lg:top-0 lg:w-1/3">
        <TraceInspector
          row={selected}
          run={run}
          providerNames={providerNames}
          onViewMessages={onViewMessages}
        />
      </div>
    </div>
  );
}
