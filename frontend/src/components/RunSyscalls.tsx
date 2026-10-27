import { useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Search } from "lucide-react";
import type { RunDetail } from "@/lib/types";
import { describeCall, safeJson } from "@/lib/callSummary";
import { toolEventStatus } from "@/lib/toolStatus";
import { JsonBlock } from "@/components/JsonBlock";
import { FilterPills } from "@/components/ui/filter-pills";

type Filter = "all" | "complete" | "failed";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function RunSyscalls({
  run,
  egress,
  tabs,
}: {
  run: RunDetail;
  /** Capability names flagged egress in the registry — powers the honest
   * "requests left this machine" count. */
  egress: Set<string>;
  tabs: React.ReactNode;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);

  const rows = useMemo(
    () =>
      run.audit_records.map((a) => {
        const args = safeJson(a.args);
        const result = safeJson(a.result);
        return {
          audit: a,
          args,
          result,
          status: toolEventStatus(a.outcome),
          summary: describeCall(a.capability_name, args, result),
        };
      }),
    [run.audit_records],
  );

  const counts = useMemo(() => {
    let complete = 0, failed = 0;
    for (const r of rows) {
      if (r.status === "complete") complete++;
      else failed++;
    }
    return { complete, failed };
  }, [rows]);

  const stats = useMemo(() => {
    let egressCount = 0, files = 0, denied = 0;
    for (const a of run.audit_records) {
      if (egress.has(a.capability_name)) egressCount++;
      if (a.effects?.includes("workspace_write")) files++;
      if (!a.allowed) denied++;
    }
    return { egressCount, files, denied };
  }, [run.audit_records, egress]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (filter === "complete" && r.status !== "complete") return false;
      if (filter === "failed" && r.status === "complete") return false;
      if (q && !`${r.audit.capability_name} ${r.summary}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rows, filter, query]);

  const toggle = (id: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  if (run.audit_records.length === 0) {
    return (
      <div>
        <div className="mb-4">{tabs}</div>
        <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No syscalls in this run</p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>{tabs}</div>
        <div className="flex flex-wrap items-center gap-2">
          <FilterPills
            variant="segmented"
            pills={[
              { key: "all", label: "All", count: rows.length },
              { key: "complete", label: "Complete", count: counts.complete },
              { key: "failed", label: "Failed", count: counts.failed },
            ]}
            active={filter}
            onChange={(k) => setFilter(k as Filter)}
          />
          <div
            className="flex h-7 items-center gap-1.5 rounded-md border px-2.5"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <Search className="h-3 w-3 text-[var(--ink-3)]" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search syscalls"
              className="w-32 bg-transparent text-[11px] outline-none placeholder:text-[var(--ink-3)]"
            />
          </div>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard.writeText(JSON.stringify(run.audit_records, null, 2)).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              });
            }}
            className="flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[11px] font-medium"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink-2)", cursor: "pointer" }}
          >
            {copied ? <Check className="h-3 w-3" style={{ color: "var(--accent)" }} /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy as JSON"}
          </button>
        </div>
      </div>

      {/* Honest roll-up — counts come from the records themselves + registry
       * egress flags, not guesses. */}
      <p className="mb-2 text-[11px] text-[var(--ink-2)]">
        <span className="font-semibold">{rows.length}</span> syscall{rows.length === 1 ? "" : "s"}
        <span className="mx-2 text-[var(--ink-3)]">·</span>
        <span className="font-semibold">{stats.egressCount}</span> request{stats.egressCount === 1 ? "" : "s"} left this machine
        <span className="mx-2 text-[var(--ink-3)]">·</span>
        <span className="font-semibold">{stats.files}</span> file{stats.files === 1 ? "" : "s"} changed
        <span className="mx-2 text-[var(--ink-3)]">·</span>
        <span className="font-semibold">{stats.denied}</span> approval{stats.denied === 1 ? "" : "s"} needed
      </p>

      <div className="overflow-hidden rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        {/* Header */}
        <div
          className="flex items-center border-b px-3 py-1.5 text-[9px] font-medium uppercase tracking-wider text-[var(--ink-3)]"
          style={{ borderColor: "var(--border)", background: "var(--ground)" }}
        >
          <span className="w-[68px] shrink-0">Time</span>
          <span className="w-[160px] shrink-0">Syscall</span>
          <span className="min-w-0 flex-1">What it did</span>
          <span className="w-[76px] shrink-0">Decision</span>
          <span className="w-[60px] shrink-0 text-right">Latency</span>
          <span className="w-5 shrink-0" />
        </div>

        {visible.map((r) => {
          const a = r.audit;
          const open = expanded.has(a.id);
          return (
            <div key={a.id} className="border-b last:border-b-0" style={{ borderColor: "var(--border-soft)" }}>
              <button
                type="button"
                onClick={() => toggle(a.id)}
                className="flex w-full items-center px-3 py-2.5 text-left transition-colors hover:bg-[var(--ground)]"
                style={{ background: "none", border: "none", cursor: "pointer" }}
                data-testid={`syscall-row-${a.id}`}
              >
                <span className="w-[68px] shrink-0 font-mono text-[10px] tabular-nums text-[var(--ink-3)]">
                  {fmtTime(a.created_at)}
                </span>
                <span className="w-[160px] shrink-0 truncate font-mono text-[11px] text-[var(--ink)]">
                  {a.capability_name}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--ink-2)]">{r.summary}</span>
                <span className="w-[76px] shrink-0">
                  <span
                    className="flex items-center gap-1 text-[10px]"
                    style={{ color: a.allowed ? "var(--accent)" : "var(--danger, #ef4444)" }}
                  >
                    <span
                      className="inline-block h-1.5 w-1.5 rounded-full"
                      style={{ background: a.allowed ? "var(--accent)" : "var(--danger, #ef4444)" }}
                    />
                    {a.allowed ? "Allowed" : "Denied"}
                  </span>
                </span>
                <span className="w-[60px] shrink-0 text-right text-[10px] tabular-nums text-[var(--ink-3)]">
                  {a.latency_ms > 0 ? `${a.latency_ms.toLocaleString()} ms` : "—"}
                </span>
                <span className="flex w-5 shrink-0 justify-end text-[var(--ink-3)]">
                  {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </span>
              </button>

              {open && (
                <div className="border-t px-3 pb-3 pt-2.5" style={{ borderColor: "var(--border-soft)", background: "var(--surface)" }}>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-[var(--ink-3)]">Args</p>
                      {r.args != null ? <JsonBlock data={r.args} /> : <p className="text-[11px] italic text-[var(--ink-3)]">Not recorded</p>}
                    </div>
                    <div>
                      <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-[var(--ink-3)]">Result</p>
                      {r.result != null ? <JsonBlock data={r.result} /> : <p className="text-[11px] italic text-[var(--ink-3)]">Not recorded</p>}
                    </div>
                  </div>
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--ink-3)]">
                    {a.call_id && <span className="font-mono">{a.call_id.slice(0, 10)}…</span>}
                    <span>
                      Decision: {a.allowed ? "allowed by policy" : a.denied_reason ? `denied — ${a.denied_reason}` : "denied"}
                    </span>
                    {a.cost > 0 ? <span>Cost ${a.cost.toFixed(6)}</span> : <span>Cost not tracked for this tool</span>}
                    {r.status !== "complete" && <span>Outcome: {r.status}</span>}
                    {a.sub_agent_id && <span>via sub-agent {a.sub_agent_id.slice(0, 8)}</span>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {visible.length === 0 && (
          <p className="py-6 text-center text-[12px] text-[var(--ink-3)]">No syscalls match</p>
        )}
      </div>
    </div>
  );
}
