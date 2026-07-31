import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { DiffBlock } from "@/components/DiffBlock";

export interface ToolCallData {
  id: string;
  capability: string;
  args: Record<string, unknown>;
  status: "pending" | "pending_approval" | "pending_input" | "running" | "complete" | "denied";
  result?: unknown;
  approval_id?: string;
  elicitation_id?: string;
}

interface ToolCallBlockProps {
  call: ToolCallData;
}

export function ToolCallBlock({ call }: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const [remember, setRemember] = useState(false);
  const [approvalState, setApprovalState] = useState<
    "pending" | "approved" | "rejected" | "error"
  >(call.status === "pending_approval" ? "pending" : "pending");

  // Auto-expand during execution, approval, or elicitation
  useEffect(() => {
    if (call.status === "pending" || call.status === "running" || call.status === "pending_approval" || call.status === "pending_input") {
      setExpanded(true);
    }
  }, [call.status]);

  const statusConfig = {
    pending: { symbol: "⋯", color: "var(--ink-3)", label: "waiting" },
    pending_approval: { symbol: "⏸", color: "var(--warning)", label: "approval" },
    pending_input: { symbol: "?", color: "var(--info, var(--warning))", label: "asking" },
    running: { symbol: "⋯", color: "var(--warning)", label: "run" },
    complete: { symbol: "✓", color: "var(--success)", label: "done" },
    denied: { symbol: "✕", color: "var(--danger)", label: "error" },
  };

  const config = statusConfig[call.status];
  const argsStr = formatArgs(call.capability, call.args);
  const hasResult =
    call.status === "complete" && call.result != null ||
    call.status === "denied";

  const handleApprove = async () => {
    if (!call.approval_id) return;
    try {
      await api.approveCall(call.approval_id, remember);
      setApprovalState("approved");
    } catch {
      setApprovalState("error");
    }
  };

  const handleReject = async () => {
    if (!call.approval_id) return;
    try {
      await api.rejectCall(call.approval_id);
      setApprovalState("rejected");
    } catch {
      setApprovalState("error");
    }
  };

  return (
    <div>
      {/* Compact single-line tool call */}
      <div
        onClick={() => hasResult && setExpanded(!expanded)}
        className="mb-2 flex items-center gap-2 rounded-[5px] border px-2.5 py-1.5"
        style={{
          background: "var(--tool-bg)",
          borderColor: call.status === "pending_approval" ? "var(--warning)" : "var(--border)",
          cursor: hasResult ? "pointer" : "default",
        }}
      >
        <span className="font-mono text-[11px] text-[var(--ink-2)]">
          {call.capability}({argsStr})
        </span>
        <span
          className={`ml-auto font-mono text-[11px] ${call.status === "running" ? "pulse" : ""}`}
          style={{ color: config.color }}
        >
          {config.symbol}
        </span>
      </div>

      {/* Approval buttons */}
      {call.status === "pending_approval" && call.approval_id && (
        <div className="mb-2 rounded-[5px] border p-2"
          style={{ borderColor: "var(--warning)", background: "var(--surface)" }}
        >
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-[var(--ink-2)]">
              {approvalState === "pending" && "Requires approval"}
              {approvalState === "approved" && "Approved — executing..."}
              {approvalState === "rejected" && "Rejected"}
              {approvalState === "error" && "Error — try again"}
            </span>
            {approvalState === "pending" && (
              <div className="ml-auto flex gap-1.5">
                <button
                  onClick={handleApprove}
                  className="rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-medium transition"
                  style={{ background: "var(--success)", color: "var(--white)", border: "none", cursor: "pointer" }}
                >
                  Approve
                </button>
                <button
                  onClick={handleReject}
                  className="rounded-[4px] px-2.5 py-1 font-mono text-[11px] font-medium transition"
                  style={{ background: "var(--danger)", color: "var(--white)", border: "none", cursor: "pointer" }}
                >
                  Deny
                </button>
              </div>
            )}
          </div>
          {approvalState === "pending" && (
            <label className="mt-1.5 flex items-center gap-1.5 font-mono text-[10px] text-[var(--ink-3)]"
              style={{ cursor: "pointer", userSelect: "none" }}
            >
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                style={{ cursor: "pointer" }}
              />
              Remember for this session
            </label>
          )}
        </div>
      )}

      {/* Elicitation — waiting for user input (the chat bar handles the actual input) */}
      {call.status === "pending_input" && call.elicitation_id && (
        <div className="mb-2 rounded-[5px] border p-2.5"
          style={{ borderColor: "var(--warning)", background: "var(--surface)" }}
        >
          <div className="font-mono text-[11px] text-[var(--ink-2)]">
            Waiting for your input in the chat bar below…
          </div>
        </div>
      )}

      {/* Diff block for file.write results */}
      {call.status === "complete" && call.capability === "file.write" && call.result &&
        typeof call.result === "object" && call.result !== null &&
        "action" in (call.result as Record<string, unknown>) && (
        <DiffBlock
          diff={(call.result as Record<string, unknown>).diff as string || ""}
          path={(call.result as Record<string, unknown>).path as string}
          action={(call.result as Record<string, unknown>).action as "created" | "modified" | "unchanged"}
        />
      )}

      {/* Expanded result — hidden for file.write (diff block replaces it) */}
      {expanded && hasResult && !(call.capability === "file.write" && call.status === "complete" && typeof call.result === "object" && call.result !== null && "action" in (call.result as Record<string, unknown>)) && (
        <div
          className="mb-2 overflow-x-auto whitespace-pre-wrap break-words rounded-[5px] p-2 font-mono text-[11px]"
          style={{
            background: "var(--white)",
            border: "1px solid var(--border)",
            color: call.status === "denied" ? "var(--danger)" : "var(--ink-2)",
          }}
        >
          {call.status === "denied"
            ? typeof call.result === "string"
              ? call.result
              : "Call was denied by the syscall layer."
            : formatResult(call.result)}
        </div>
      )}
    </div>
  );
}

function formatArgs(
  capability: string,
  args: Record<string, unknown>,
): string {
  if (capability === "shell.run" && args.command) {
    return `"${args.command}"`;
  }
  if (capability.startsWith("file.")) {
    const parts: string[] = [];
    if (args.path) parts.push(`"${args.path}"`);
    if (args.content) {
      const c = String(args.content);
      parts.push(`"${c.length > 50 ? c.slice(0, 50) + "..." : c}"`);
    }
    return parts.join(", ");
  }
  return JSON.stringify(args).slice(0, 80);
}

function formatResult(result: unknown): string {
  if (typeof result === "string") return result;
  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;
    if ("stdout" in obj || "stderr" in obj) {
      const lines: string[] = [];
      if (obj.stdout) lines.push(String(obj.stdout));
      if (obj.stderr) lines.push(String(obj.stderr));
      if ("exit_code" in obj) lines.push(`[exit code: ${obj.exit_code}]`);
      return lines.join("\n");
    }
    if ("entries" in obj && Array.isArray(obj.entries)) {
      return (obj.entries as Array<{ name: string; type: string; size: number }>)
        .map((e) => `${e.type === "dir" ? "📁" : "📄"} ${e.name} (${e.size} bytes)`)
        .join("\n");
    }
  }
  return JSON.stringify(result, null, 2);
}
