import type { TraceRow } from "./traceLayout";

/** Envelope events the default trace view hides — the root row and the
 * inspector already cover them; "Show events" reveals everything. */
export const ENVELOPE_TYPES = new Set([
  "run_started",
  "run_completed",
  "manifest",
]);

export const TYPE_LABEL: Record<string, string> = {
  run_started: "run started",
  run_completed: "run finished",
  manifest: "manifest",
  model_call: "Generation",
  tool_call: "tool",
  capability_load: "capability load",
  retrieval: "retrieval",
  approval: "approval",
  approval_decision: "approval decision",
  elicitation: "elicitation",
  elicitation_decision: "elicitation answered",
  terminal: "terminal",
  terminal_completed: "terminal finished",
  browser_evidence: "browser",
  citation: "citation",
  artifact_revision: "artifact",
  schedule_occurrence: "schedule",
  notification: "notification",
  notification_delivery: "delivery",
};

/** Subtle per-kind bar hues — theme vars with hard fallbacks. */
const KIND_HUE: Record<string, string> = {
  model_call: "var(--accent, #6b6d3f)",
  tool_call: "var(--chart-2, #64748b)",
  retrieval: "var(--chart-4, #7c8a6a)",
  approval: "var(--warning, #b08968)",
  approval_decision: "var(--warning, #b08968)",
  elicitation: "var(--warning, #b08968)",
  terminal: "var(--chart-3, #78716c)",
  terminal_completed: "var(--chart-3, #78716c)",
  browser_evidence: "var(--chart-5, #8a8577)",
  citation: "var(--ink-3, #a8a29e)",
  artifact_revision: "var(--brand, #6b6d3f)",
};

export function spanHue(type: string): string {
  return KIND_HUE[type] ?? "var(--ink-3, #a8a29e)";
}

export function fmtMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

export function fmtCostValue(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return "Not reported";
  return cost < 0.01 ? `$${cost.toFixed(6)}` : `$${cost.toFixed(4)}`;
}

/** Primary row label: model generations get provider/model; tools get
 * the capability name; everything else a friendly type name. Never a
 * raw snake_case tag. */
export function spanLabel(
  row: TraceRow,
  providerNames: Record<string, string>,
): string {
  const event = row.event;
  if (event === null) return "Run";
  const d = event.data || {};
  if (event.type === "model_call") {
    const providerId = typeof d.provider_id === "string" ? d.provider_id : null;
    const provider =
      (providerId && providerNames[providerId]) ||
      (providerId ? "Unknown provider" : "provider");
    const model = d.model_name ?? d.model_str;
    return `Generation ${provider} / ${model ? String(model) : "unknown model"}`;
  }
  if (event.type === "tool_call" && typeof d.capability === "string") {
    return d.capability;
  }
  return TYPE_LABEL[event.type] || event.type;
}

/** Free-text search corpus for a row. */
export function spanSearchText(
  row: TraceRow,
  providerNames: Record<string, string>,
): string {
  const event = row.event;
  if (event === null) return "run";
  const d = event.data || {};
  const providerId = typeof d.provider_id === "string" ? d.provider_id : "";
  return [
    spanLabel(row, providerNames),
    event.type,
    event.status ?? "",
    providerId,
    providerNames[providerId] ?? "",
    String(d.capability ?? ""),
    String(d.model_name ?? ""),
    String(d.model_str ?? ""),
    String(d.purpose ?? ""),
    String(d.kind ?? ""),
    event.call_id ?? "",
    event.sub_agent_id ?? "",
  ]
    .join(" ")
    .toLowerCase();
}

export function timingLabel(row: TraceRow): string {
  if (row.timing === "derived") return "derived";
  if (row.timing === "observed") return "observed";
  if (row.timing === "point") return "instant";
  return "unknown";
}

/** Where a tool row's record came from — audit row vs. tombstone
 * tool_call message vs. pending approval. */
export function originLabel(row: TraceRow): string | null {
  const event = row.event;
  if (event === null || event.type !== "tool_call") return null;
  const d = event.data || {};
  if (typeof d.audit_id === "string") return "Audit record";
  if (event.status === "pending_approval") return "Pending approval";
  return "Tool message";
}
