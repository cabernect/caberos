import { useState } from "react";
import { api } from "@/lib/api";
import { DiffBlock } from "@/components/DiffBlock";
import { ThinkingBlock } from "@/components/ThinkingBlock";

export interface ToolCallData {
  id: string;
  capability: string;
  args: Record<string, unknown>;
  status: "pending" | "pending_approval" | "pending_input" | "running" | "complete" | "denied";
  result?: unknown;
  approval_id?: string;
  elicitation_id?: string;
}

export interface SubAgentStreamData {
  thinking: string;
  items: { type: "thinking" | "tool"; id: string; data: ThinkingBlockData | ToolCallData }[];
  text: string;
  completed: boolean;
}

interface ThinkingBlockData {
  content: string;
  durationSec: number | null;
}

interface ToolCallBlockProps {
  call: ToolCallData;
  subagentStream?: SubAgentStreamData;
}

export function ToolCallBlock({ call, subagentStream }: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const [subExpanded, setSubExpanded] = useState(false);
  const [remember, setRemember] = useState(false);
  const [approvalState, setApprovalState] = useState<
    "pending" | "approved" | "rejected" | "error"
  >(call.status === "pending_approval" ? "pending" : "pending");

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

  const isSubagent = call.capability === "run_subagent";

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
      {!isSubagent && (
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
            {`${call.capability}(${argsStr})`}
          </span>
          <span
            className={`ml-auto font-mono text-[11px] ${call.status === "running" ? "pulse" : ""}`}
            style={{ color: config.color }}
          >
            {config.symbol}
          </span>
        </div>
      )}

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

      {/* Diff block for write_file results */}
      {call.status === "complete" && call.capability === "write_file" && call.result &&
        typeof call.result === "object" && call.result !== null &&
        "action" in (call.result as Record<string, unknown>) && (
        <DiffBlock
          diff={(call.result as Record<string, unknown>).diff as string || ""}
          path={(call.result as Record<string, unknown>).path as string}
          action={(call.result as Record<string, unknown>).action as "created" | "modified" | "unchanged"}
        />
      )}

      {/* Expanded result — hidden for write_file (diff block replaces it)
          and run_subagent (the nested sub-agent stream replaces it) */}
      {expanded && hasResult &&
        !(call.capability === "write_file" && call.status === "complete" && typeof call.result === "object" && call.result !== null && "action" in (call.result as Record<string, unknown>)) &&
        !(isSubagent && subagentStream && (subagentStream.items.length > 0 || subagentStream.text)) && (
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

      {isSubagent && (
        <div
          className="mb-2 rounded-[5px] border p-2.5"
          style={{ borderColor: "var(--border)", background: "var(--surface)", marginLeft: "12px" }}
        >
          <button
            onClick={() => setSubExpanded(!subExpanded)}
            className="flex w-full items-center gap-1.5 bg-none p-0 text-left"
            style={{ border: "none", cursor: "pointer" }}
          >
            <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
              sub-agent {subagentStream?.completed ? "✓ done" : "running…"}
            </span>
            <span className="ml-auto font-mono text-[10px] text-[var(--ink-3)]">{subExpanded ? "▲" : "▼"}</span>
            <span
              className={`font-mono text-[11px] ${call.status === "running" ? "pulse" : ""}`}
              style={{ color: config.color }}
            >
              {config.symbol}
            </span>
          </button>

          {subExpanded && (
            <>
              <div
                className="mb-2 mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-[5px] p-2 font-mono text-[11px]"
                style={{ background: "var(--white)", border: "1px solid var(--border)", color: "var(--ink-2)" }}
              >
                Task: {String(call.args.task || "No task provided")}
              </div>
              {subagentStream?.items.map((item) => {
                if (item.type === "thinking") {
                  const td = item.data as ThinkingBlockData;
                  return <ThinkingBlock key={item.id} content={td.content} isStreaming={false} durationSec={td.durationSec ?? undefined} />;
                }
                const td = item.data as ToolCallData;
                return <ToolCallBlock key={item.id} call={td} />;
              })}
              {subagentStream?.thinking && (
                <ThinkingBlock content={subagentStream.thinking} isStreaming={!subagentStream.completed} />
              )}
              {subagentStream?.text && (
                <div className="whitespace-pre-wrap break-words text-[12px] text-[var(--ink-1)]">
                  {subagentStream.text}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function formatArgs(
  capability: string,
  args: Record<string, unknown>,
): string {
  if (capability === "terminal" && args.command) {
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
