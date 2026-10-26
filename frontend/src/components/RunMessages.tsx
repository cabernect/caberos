import { useMemo, useState } from "react";
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  Globe,
  Sparkles,
  Terminal,
  User,
  Wrench,
} from "lucide-react";
import type { AuditOut, MessageOut, RunDetail } from "@/lib/types";
import { asObj, describeCall, hostOf, safeJson } from "@/lib/callSummary";
import { toolEventStatus } from "@/lib/toolStatus";
import { JsonBlock } from "@/components/JsonBlock";
import { Markdown } from "@/components/Markdown";
import { FilterPills } from "@/components/ui/filter-pills";

type Filter = "all" | "user" | "agent" | "tools";

const CAP_ICONS: [RegExp, typeof Globe][] = [
  [/^skills_/, Sparkles],
  [/datetime/, Clock],
  [/web_fetch|web_search|browser/, Globe],
  [/terminal/, Terminal],
  [/file|search_files|artifact/, FileText],
  [/memory/, Brain],
];

function capIcon(name: string) {
  for (const [re, Icon] of CAP_ICONS) if (re.test(name)) return Icon;
  return Wrench;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtDeltaMs(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `+${s}s`;
}

interface ToolPayload {
  id?: string;
  capability?: string;
  status?: string;
  args?: unknown;
  result?: unknown;
}

function CopyButton({ json, label }: { json: unknown; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(JSON.stringify(json, null, 2)).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[11px] font-medium transition-colors"
      style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink-2)", cursor: "pointer" }}
    >
      {copied ? <Check className="h-3 w-3" style={{ color: "var(--accent)" }} /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

export function RunMessages({
  run,
  tabs,
}: {
  run: RunDetail;
  tabs: React.ReactNode;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const agentName = run.agent_name ?? run.agent_id;

  const auditByCallId = useMemo(() => {
    const m = new Map<string, AuditOut>();
    for (const a of run.audit_records) if (a.call_id) m.set(a.call_id, a);
    return m;
  }, [run.audit_records]);

  const counts = useMemo(() => {
    let user = 0, agent = 0, tools = 0;
    for (const m of run.messages) {
      if (m.role === "user") user++;
      else if (m.role === "tool_call") tools++;
      else agent++;
    }
    return { user, agent, tools };
  }, [run.messages]);

  const visible = useMemo(
    () =>
      run.messages.filter((m) => {
        if (filter === "user") return m.role === "user";
        if (filter === "tools") return m.role === "tool_call";
        if (filter === "agent") return m.role !== "user" && m.role !== "tool_call";
        return true;
      }),
    [run.messages, filter],
  );

  const toolIds = useMemo(() => visible.filter((m) => m.role === "tool_call").map((m) => m.id), [visible]);
  const allExpanded = toolIds.length > 0 && toolIds.every((id) => expanded.has(id));

  const toggle = (id: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  let prevTs: number | null = null;

  return (
    <div>
      {/* Tab pills on the left, message controls on the right — same row. */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>{tabs}</div>
        <div className="flex flex-wrap items-center gap-2">
          <FilterPills
            variant="segmented"
            pills={[
              { key: "all", label: "All" },
              { key: "user", label: "You", count: counts.user },
              { key: "agent", label: agentName, count: counts.agent },
              { key: "tools", label: "Tool calls", count: counts.tools },
            ]}
            active={filter}
            onChange={(k) => setFilter(k as Filter)}
          />
          <button
            type="button"
            onClick={() => setExpanded(allExpanded ? new Set() : new Set(toolIds))}
            className="flex h-7 items-center rounded-md border px-2.5 text-[11px] font-medium"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink-2)", cursor: "pointer" }}
          >
            {allExpanded ? "Collapse all" : "Expand all"}
          </button>
          <CopyButton json={run.messages} label="Copy as JSON" />
        </div>
      </div>

      <div className="space-y-2.5">
        {visible.map((m) => {
          const ts = Date.parse(m.created_at);
          const delta = prevTs !== null && Number.isFinite(ts) ? ts - prevTs : null;
          if (Number.isFinite(ts)) prevTs = ts;
          return (
            <div key={m.id} className="flex gap-3">
              {/* Time rail */}
              <div className="w-[72px] shrink-0 pt-3 text-right">
                <p className="text-[10px] tabular-nums text-[var(--ink-3)]">{fmtTime(m.created_at)}</p>
                {delta !== null && delta > 0 && (
                  <p className="text-[9px] tabular-nums text-[var(--ink-3)]">{fmtDeltaMs(delta)}</p>
                )}
              </div>

              <MessageCard
                m={m}
                agentName={agentName}
                auditFor={(callId) => auditByCallId.get(callId)}
                expanded={expanded.has(m.id)}
                onToggle={() => toggle(m.id)}
              />
            </div>
          );
        })}
        {visible.length === 0 && (
          <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No messages match this filter</p>
        )}
      </div>
    </div>
  );
}

function MessageCard({
  m,
  agentName,
  auditFor,
  expanded,
  onToggle,
}: {
  m: MessageOut;
  agentName: string;
  auditFor: (callId: string) => AuditOut | undefined;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isUser = m.role === "user";
  const isTool = m.role === "tool_call";
  const payload: ToolPayload | null = isTool ? (asObj(safeJson(m.content)) as ToolPayload | null) : null;
  const capability = payload?.capability ?? "tool_call";
  const Icon = isUser ? User : isTool ? capIcon(capability) : Bot;
  const name = isUser ? "You" : isTool ? capability : m.role === "thinking" ? `${agentName} · thinking` : agentName;
  const audit = payload?.id ? auditFor(payload.id) : undefined;
  const status = audit ? toolEventStatus(audit.outcome) : (payload?.status ?? null);
  const latencyMs = audit?.latency_ms ?? null;
  const args = payload?.args;
  const result = payload?.result;
  const expandable = isTool && (args != null || result != null);
  const host = hostOf((asObj(args)?.url as string | undefined) ?? (asObj(result)?.url as string | undefined));

  return (
    <div
      className="min-w-0 flex-1 rounded-lg border transition-colors"
      style={{
        borderColor: expanded ? "var(--accent)" : "var(--border)",
        background: "var(--surface)",
      }}
    >
      <button
        type="button"
        onClick={expandable ? onToggle : undefined}
        className="flex w-full items-start gap-2.5 px-3.5 py-3 text-left"
        style={{ cursor: expandable ? "pointer" : "default", background: "none", border: "none" }}
      >
        <span
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
          style={{ background: "var(--ground)", color: "var(--ink-2)" }}
        >
          {isTool || isUser ? (
            <Icon className="h-3.5 w-3.5" />
          ) : (
            <span className="text-[10px] font-semibold">{agentName.slice(0, 1).toUpperCase()}</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span
              className="text-[12px] font-semibold"
              style={{ color: isTool ? "var(--ink)" : "var(--ink-2)", fontFamily: isTool ? "monospace" : undefined }}
            >
              {name}
            </span>
            {host && (
              <span
                className="flex items-center gap-1 rounded-full px-1.5 py-px text-[9px]"
                style={{ background: "var(--accent-bg, rgba(107,109,63,0.10))", color: "var(--accent)" }}
              >
                <ExternalLink className="h-2.5 w-2.5" />
                {host}
              </span>
            )}
            {m.subagent_id && (
              <span className="rounded-[3px] px-1 text-[9px] text-[var(--ink-3)]" style={{ border: "1px solid var(--border)" }}>
                sub {m.subagent_id.slice(0, 6)}
              </span>
            )}
          </div>
          <div
            className="mt-0.5 break-words text-[12px]"
            style={{ color: m.role === "thinking" ? "var(--ink-3)" : "var(--ink-2)", fontStyle: m.role === "thinking" ? "italic" : undefined }}
          >
            {isTool && payload ? (
              <p className="whitespace-pre-wrap">{describeCall(capability, args, result)}</p>
            ) : (
              <Markdown>{m.content}</Markdown>
            )}
          </div>
        </div>
        {isTool && (
          <div className="flex shrink-0 items-center gap-2.5 pt-0.5">
            {latencyMs !== null && latencyMs > 0 && (
              <span className="text-[10px] tabular-nums text-[var(--ink-3)]">{latencyMs.toLocaleString()} ms</span>
            )}
            {status && (
              <span className="flex items-center gap-1 text-[10px] font-medium" style={{ color: status === "complete" ? "var(--accent)" : "var(--warning, #b08968)" }}>
                <Check className="h-3 w-3" />
                {status.slice(0, 1).toUpperCase() + status.slice(1)}
              </span>
            )}
            {expandable &&
              (expanded ? (
                <ChevronDown className="h-3.5 w-3.5 text-[var(--ink-3)]" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 text-[var(--ink-3)]" />
              ))}
          </div>
        )}
      </button>

      {expanded && expandable && (
        <div className="border-t px-3.5 pb-3 pt-2.5" style={{ borderColor: "var(--border)" }}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-[var(--ink-3)]">Args</p>
              {args != null ? <JsonBlock data={args} /> : <p className="text-[11px] italic text-[var(--ink-3)]">Not recorded</p>}
            </div>
            <div>
              <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-[var(--ink-3)]">Result</p>
              {result != null ? <JsonBlock data={result} /> : <p className="text-[11px] italic text-[var(--ink-3)]">Not recorded</p>}
            </div>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--ink-3)]">
            {payload?.id && <span className="font-mono">{payload.id.slice(0, 10)}…</span>}
            {audit && audit.cost > 0 ? <span>Cost ${audit.cost.toFixed(6)}</span> : <span>Cost not tracked for this tool</span>}
            {audit?.sub_agent_id && <span>via sub-agent {audit.sub_agent_id.slice(0, 8)}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
