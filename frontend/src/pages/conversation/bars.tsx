import {
  AlertCircle,
  BarChart3,
  CheckCircle,
  Loader2,
  X,
} from "lucide-react";
import type { CompactStatus, ContextInfo } from "./types";

export function ContextInfoBar({
  info,
  onDismiss,
}: {
  info: ContextInfo;
  onDismiss: () => void;
}) {
  const pct =
    info.state === "ready" && info.contextTokens != null && info.maxContextTokens
      ? Math.round((info.contextTokens / info.maxContextTokens) * 100)
      : null;
  const fmt = (n?: number) => (n != null ? n.toLocaleString() : "—");
  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-2 rounded-lg px-3 py-2 text-[13px]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        color: "var(--ink-2)",
      }}
    >
      <div className="flex items-center gap-2">
        {info.state === "loading" ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin" style={{ color: "var(--accent)" }} />
        ) : (
          <BarChart3 className="h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
        )}
        <span className="min-w-0 flex-1">
          {info.state === "loading" && "Loading context usage…"}
          {info.state === "empty" && "No runs yet — context usage appears after the first run."}
          {info.state === "error" && `Context lookup failed — ${info.message ?? "unknown error"}`}
          {info.state === "ready" && (
            <>
              Context — {fmt(info.contextTokens)} / {fmt(info.maxContextTokens)} tokens
              {pct != null && ` (${pct}%)`}
              {info.compacted && (
                <span className="ml-1.5 rounded px-1 py-px font-mono text-[10px]" style={{ background: "var(--ground)", color: "var(--ink-3)" }}>
                  compacted
                </span>
              )}
            </>
          )}
        </span>
        {info.state !== "loading" && (
          <button
            onClick={onDismiss}
            aria-label="Dismiss context info"
            className="shrink-0 rounded p-0.5"
            style={{ color: "var(--ink-3)" }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {info.state === "ready" && info.breakdown && (
        <div className="mt-1 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          system {fmt(info.breakdown.system_prompt)} · conversation {fmt(info.breakdown.conversation)} · tools {fmt(info.breakdown.tools)}
          {info.asOf && ` — as of last run ${new Date(info.asOf).toLocaleString()}`}
        </div>
      )}
    </div>
  );
}

// Pinned above the composer so progress/outcome stays visible regardless of
// where the message list is scrolled. aria-live announces state changes.
export function CompactStatusBar({
  status,
  onRetry,
  onDismiss,
}: {
  status: CompactStatus;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const isError = status.state === "failed";
  return (
    <div
      role={isError ? "alert" : "status"}
      aria-live="polite"
      className="mb-2 flex items-center gap-2 rounded-lg px-3 py-2 text-[13px]"
      style={{
        background: "var(--surface)",
        border: `1px solid ${isError ? "var(--warning)" : "var(--border)"}`,
        color: "var(--ink-2)",
      }}
    >
      {status.state === "pending" && (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" style={{ color: "var(--accent)" }} />
      )}
      {status.state === "succeeded" && (
        <CheckCircle className="h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
      )}
      {(status.state === "failed" || status.state === "unchanged") && (
        <AlertCircle className="h-4 w-4 shrink-0" style={{ color: isError ? "var(--warning)" : "var(--ink-3)" }} />
      )}
      <span className="min-w-0 flex-1">
        {status.state === "pending" && "Compacting conversation…"}
        {status.state === "succeeded" &&
          `Context compacted — ${status.originalTokens?.toLocaleString() ?? "?"} → ${status.compactedTokens?.toLocaleString() ?? "?"} estimated tokens`}
        {status.state === "unchanged" &&
          "Nothing to compact — the conversation already fits in context."}
        {status.state === "failed" &&
          `Compaction failed — ${status.message ?? "unknown error"}`}
      </span>
      {status.state === "failed" && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded px-2 py-0.5 text-[12px] font-medium"
          style={{ background: "var(--accent)", color: "var(--white)" }}
        >
          Retry
        </button>
      )}
      {status.state !== "pending" && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss compaction status"
          className="shrink-0 rounded p-0.5"
          style={{ color: "var(--ink-3)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
