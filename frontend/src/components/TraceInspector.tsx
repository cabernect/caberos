import { useState } from "react";
import type { RunDetail, TimelineEvent } from "@/lib/types";
import type { TraceRow } from "@/lib/traceLayout";
import { fmtCostValue, fmtMs, originLabel, spanLabel, timingLabel, TYPE_LABEL } from "@/lib/traceFormat";

type Tab = "overview" | "input" | "output" | "metadata";

const NO_IO_TEXT =
  "Per-call request/response was not recorded — only usage metadata is captured. Run messages show the conversation, not the full model prompt/context.";

function Pill({ children, tone }: { children: string; tone?: "warn" | "muted" }) {
  return (
    <span
      className="rounded-[3px] px-1.5 py-0.5 text-[9px]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        color: tone === "warn" ? "var(--warning, #b08968)" : "var(--ink-3)",
      }}
    >
      {children}
    </span>
  );
}

/** Structured key/value rendering — readable first, raw JSON behind a
 * disclosure. Values are already projected/bounded server-side. */
function KeyValue({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0)
    return <p className="text-[11px] italic text-[var(--ink-3)]">No data recorded.</p>;
  return (
    <div>
      <dl className="space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-0.5">
            <dt className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">{k}</dt>
            <dd className="min-w-0 text-[11px] text-[var(--ink)]">
              {typeof v === "object" ? (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-[4px] p-1.5 font-mono text-[10px]" style={{ background: "var(--surface)" }}>
                  {JSON.stringify(v, null, 1)}
                </pre>
              ) : (
                <span className="break-all">{String(v)}</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <details className="mt-2">
        <summary className="cursor-pointer text-[10px] text-[var(--ink-3)] select-none">JSON</summary>
        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-[4px] p-1.5 font-mono text-[10px]" style={{ background: "var(--surface)" }}>
          {JSON.stringify(data, null, 1)}
        </pre>
      </details>
    </div>
  );
}

function pick(event: TimelineEvent, keys: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const d = event.data || {};
  for (const k of keys) if (d[k] !== undefined && d[k] !== null) out[k] = d[k];
  return out;
}

/** What each event type offers as Input/Output. Model calls are honest
 * about the capture gap; tools show their projected args/result. */
function ioFor(row: TraceRow): { input: unknown; output: unknown } {
  const event = row.event;
  if (event === null) return { input: null, output: null };
  const d = event.data || {};
  const status = event.status ? { status: event.status } : {};
  switch (event.type) {
    case "tool_call":
      return {
        input: typeof d.args === "object" && d.args !== null ? d.args : { args: d.args },
        output: {
          ...status,
          ...(typeof d.result === "object" && d.result !== null ? d.result : { result: d.result }),
          ...(typeof d.reason === "string" ? { reason: d.reason } : {}),
        },
      };
    case "retrieval":
      return {
        input: pick(event, ["query"]),
        output: { ...status, ...pick(event, ["trace", "count", "results"]) },
      };
    case "approval":
      return { input: pick(event, ["args"]), output: { ...status, ...pick(event, ["reason"]) } };
    case "approval_decision":
      return {
        input: pick(event, ["args"]),
        output: { ...status, ...pick(event, ["decided_by", "reason"]) },
      };
    case "elicitation":
      return { input: pick(event, ["question", "options"]), output: { ...status } };
    case "elicitation_decision":
      // The user's actual answer is intentionally never projected.
      return { input: pick(event, ["question"]), output: { ...status, ...pick(event, ["responded_by"]) } };
    case "terminal":
      return { input: pick(event, ["command", "cwd"]), output: { ...status } };
    case "terminal_completed":
      return {
        input: pick(event, ["command"]),
        output: { ...status, ...pick(event, ["exit_code", "stdout_bytes", "stderr_bytes"]) },
      };
    case "browser_evidence":
      return {
        input: pick(event, ["action", "url"]),
        output: { ...status, ...pick(event, ["evidence", "screenshot", "bytes"]) },
      };
    case "artifact_revision":
      return {
        input: pick(event, ["change_summary"]),
        output: {
          ...status,
          ...pick(event, ["artifact_id", "revision_number", "path", "format", "size_bytes", "content_hash"]),
        },
      };
    case "capability_load":
      return { input: null, output: { ...status, ...pick(event, ["capabilities"]) } };
    case "citation":
      return {
        input: pick(event, ["chunk_id"]),
        output: {
          ...status,
          ...pick(event, ["document_id", "source_path", "heading_path", "page_number", "sheet_name", "excerpt", "rank"]),
        },
      };
    default:
      return { input: null, output: null };
  }
}

export function TraceInspector({
  row,
  run,
  providerNames,
  onViewMessages,
}: {
  row: TraceRow;
  run?: RunDetail;
  providerNames: Record<string, string>;
  onViewMessages?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const event = row.event;
  const isRoot = event === null;
  const isModel = event?.type === "model_call";
  const { input, output } = ioFor(row);
  const d = event?.data ?? {};

  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "input", label: "Input" },
    { key: "output", label: "Output" },
    { key: "metadata", label: "Metadata" },
  ];

  return (
    <div
      className="flex min-w-0 flex-col rounded-[6px] border"
      style={{ borderColor: "var(--border)", background: "var(--white)" }}
      data-testid="trace-inspector"
    >
      {/* Header */}
      <div className="border-b px-3 py-2" style={{ borderColor: "var(--border)" }}>
        <p className="truncate text-[12px] font-semibold text-[var(--ink)]">
          {spanLabel(row, providerNames)}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {event?.status && <Pill>{event.status}</Pill>}
          {event?.redacted && <Pill tone="warn">redacted</Pill>}
          {event?.truncated && <Pill>truncated</Pill>}
          {(row.timing === "derived" || event?.estimated_time) && <Pill tone="warn">{timingLabel(row)}</Pill>}
          {row.timing === "unknown" && <Pill>unknown time</Pill>}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b px-2 py-1" style={{ borderColor: "var(--border)" }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            aria-pressed={tab === t.key}
            className="rounded-[4px] px-2 py-1 text-[11px]"
            style={{
              background: tab === t.key ? "var(--accent, #6b6d3f)" : "transparent",
              color: tab === t.key ? "var(--accent-text, var(--accent-foreground, white))" : "var(--ink-2)",
              border: "none",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-3 py-2">
        {tab === "overview" && (
          <div className="space-y-1.5 text-[11px]">
            {isRoot && run && (
              <>
                <Row k="Status" v={run.status} />
                <Row k="Trigger" v={run.trigger} />
                <Row k="Started" v={new Date(run.started_at).toLocaleString()} />
                <Row k="Completed" v={run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"} />
                <Row k="Duration" v={fmtMs(run.latency_ms)} />
                <Row k="Cost" v={fmtCostValue(run.cost)} />
                <Row k="Tokens" v={`${run.tokens_in.toLocaleString()} in / ${run.tokens_out.toLocaleString()} out`} />
                {run.error && <Row k="Error" v={run.error} />}
                {run.manifest && (
                  <div className="mt-2 border-t pt-1.5" style={{ borderColor: "var(--border)" }}>
                    <p className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">Manifest pins</p>
                    <Row
                      k="Model"
                      v={`${
                        providerNames[run.manifest.model_provider_id ?? ""] ??
                        (run.manifest.model_provider_id ? "Unknown provider" : "?")
                      }/${run.manifest.model_name ?? "?"}`}
                    />
                    <Row k="Agent rev" v={`v${run.manifest.agent_version_number ?? "?"}`} />
                    <Row
                      k="Skills"
                      v={
                        Array.isArray(run.manifest.skill_revision_ids)
                          ? run.manifest.skill_revision_ids.join(", ") || "—"
                          : Object.entries(run.manifest.skill_revision_ids)
                              .map(([n, r]) => `${n}@${String(r).slice(0, 8)}`)
                              .join(", ") || "—"
                      }
                    />
                    <Row k="Knowledge snapshots" v={String((run.manifest.knowledge_snapshot_ids ?? []).length)} />
                    <Row k="Artifact bases" v={String((run.manifest.artifact_base_revision_ids ?? []).length)} />
                  </div>
                )}
                {onViewMessages && (
                  <button
                    onClick={onViewMessages}
                    className="mt-2 rounded-[4px] px-2.5 py-1.5 text-[11px] font-medium"
                    style={{ background: "var(--accent, #6b6d3f)", color: "var(--accent-text, white)", border: "none", cursor: "pointer" }}
                  >
                    View run messages
                  </button>
                )}
              </>
            )}
            {!isRoot && event && (
              <>
                <Row k="Type" v={TYPE_LABEL[event.type] ?? event.type} />
                {originLabel(row) && <Row k="Origin" v={originLabel(row)!} />}
                <Row k="Status" v={event.status ?? "—"} />
                <Row k="Duration" v={row.durationMs !== null ? fmtMs(row.durationMs) : "—"} />
                <Row
                  k="Timing"
                  v={
                    row.timing === "derived"
                      ? "derived — placed from recorded latency, not instrumented boundaries"
                      : timingLabel(row)
                  }
                />
                {event.at ? (
                  <Row k="Recorded at" v={new Date(event.at).toLocaleString()} />
                ) : (
                  <Row k="Recorded at" v="Unknown time" />
                )}
                {isModel && (
                  <>
                    <Row k="Tokens in" v={Number(d.tokens_in ?? 0).toLocaleString()} />
                    <Row k="Tokens out" v={Number(d.tokens_out ?? 0).toLocaleString()} />
                    <Row
                      k="Thinking tokens"
                      v={
                        d.thinking_tokens === null || d.thinking_tokens === undefined
                          ? "Not reported"
                          : String(d.thinking_tokens)
                      }
                    />
                    <Row k="Cached tokens" v={d.cached_tokens === null || d.cached_tokens === undefined ? "Not reported" : String(d.cached_tokens)} />
                    <Row k="Cost" v={fmtCostValue(typeof d.cost === "number" ? d.cost : null)} />
                    <Row k="Streamed" v={d.streamed === undefined || d.streamed === null ? "Not reported" : String(d.streamed)} />
                    {typeof (d.detail as Record<string, unknown> | undefined)?.cost_source === "string" && (
                      <Row k="Cost source" v={String((d.detail as Record<string, unknown>).cost_source)} />
                    )}
                  </>
                )}
                {event.call_id && <Row k="Call" v={event.call_id} />}
                {event.sub_agent_id && <Row k="Sub-agent" v={event.sub_agent_id} />}
                {event.parent_id && <Row k="Parent" v={event.parent_id} />}
                {typeof d.capability === "string" && <Row k="Capability" v={d.capability} />}
              </>
            )}
          </div>
        )}

        {tab === "input" &&
          (isModel ? (
            <Honest text={NO_IO_TEXT} onViewMessages={onViewMessages} />
          ) : isRoot ? (
            <RunMessages run={run} roles={["user"]} />
          ) : input && Object.keys(input).length ? (
            <KeyValue data={input as Record<string, unknown>} />
          ) : (
            <Empty label="No input recorded." />
          ))}

        {tab === "output" &&
          (isModel ? (
            <Honest text={NO_IO_TEXT} onViewMessages={onViewMessages} />
          ) : isRoot ? (
            <RunMessages run={run} roles={["assistant", "thinking"]} />
          ) : output && Object.keys(output).length ? (
            <KeyValue data={output as Record<string, unknown>} />
          ) : (
            <Empty label="No output recorded." />
          ))}

        {tab === "metadata" &&
          (isRoot ? (
            <KeyValue
              data={{
                id: run?.id,
                agent: run?.agent_name ?? run?.agent_id,
                session: run?.session_id,
                is_test: run?.is_test,
                manifest: run?.manifest,
              }}
            />
          ) : (
            <KeyValue
              data={{
                id: event!.id,
                type: event!.type,
                at: event!.at,
                call_id: event!.call_id,
                sub_agent_id: event!.sub_agent_id,
                parent_id: event!.parent_id,
                ...d,
              }}
            />
          ))}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <span className="w-32 shrink-0 text-[10px] uppercase tracking-wide text-[var(--ink-3)]">{k}</span>
      <span className="min-w-0 break-all text-[var(--ink)]">{v}</span>
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <p className="text-[11px] italic text-[var(--ink-3)]">{label}</p>;
}

function Honest({ text, onViewMessages }: { text: string; onViewMessages?: () => void }) {
  return (
    <div>
      <p className="text-[11px] text-[var(--ink-2)]">{text}</p>
      {onViewMessages && (
        <button
          onClick={onViewMessages}
          className="mt-2 rounded-[4px] px-2 py-1 text-[11px]"
          style={{ border: "1px solid var(--border)", background: "var(--white)", color: "var(--ink-2)", cursor: "pointer" }}
        >
          View run messages
        </button>
      )}
    </div>
  );
}


function RunMessages({ run, roles }: { run?: RunDetail; roles: string[] }) {
  const msgs = (run?.messages ?? []).filter((m) => roles.includes(m.role));
  if (msgs.length === 0)
    return <p className="text-[11px] italic text-[var(--ink-3)]">No run messages in this direction.</p>;
  return (
    <div className="space-y-2">
      <p className="text-[9px] uppercase tracking-wide text-[var(--ink-3)]">
        Run messages — not the full model request
      </p>
      {msgs.map((m) => (
        <div key={m.id}>
          <div className="flex gap-2 text-[9px] text-[var(--ink-3)]">
            <span className="uppercase">{m.role}</span>
            {m.created_at && <span>{new Date(m.created_at).toLocaleString()}</span>}
          </div>
          <pre className="whitespace-pre-wrap break-all text-[11px] text-[var(--ink)]">{m.content}</pre>
        </div>
      ))}
    </div>
  );
}
