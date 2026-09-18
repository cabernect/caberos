import { useState } from "react";
import { Eye, FileText } from "lucide-react";
import { api, type PreviewSource } from "@/lib/api";
import { DiffBlock } from "@/components/DiffBlock";
import { ThinkingBlock } from "@/components/ThinkingBlock";

export interface ToolCallData {
  id: string;
  capability: string;
  args: Record<string, unknown>;
  status:
    | "pending"
    | "pending_approval"
    | "pending_input"
    | "running"
    | "complete"
    | "denied"
    | "failed"
    | "timeout"
    | "interrupted";
  result?: unknown;
  approval_id?: string;
  approval_batch_id?: string;
  approval_batch_size?: number;
  elicitation_id?: string;
}

export interface SubAgentStreamData {
  thinking: string;
  items: {
    type: "thinking" | "tool" | "text";
    id: string;
    data: ThinkingBlockData | ToolCallData | { content: string };
  }[];
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
  /** Opens the shared preview panel for the file/artifact this call touched. */
  onPreview?: (source: PreviewSource) => void;
}

/**
 * Resolve the preview target a completed call touched, if any:
 * artifact_* results carry artifact/revision ids; file tools carry a
 * workspace path. Returns null when nothing previewable exists.
 */
export function previewSourceFor(call: ToolCallData): PreviewSource | null {
  if (call.status !== "complete") return null;
  const result = (call.result ?? {}) as Record<string, unknown>;
  if (call.capability.startsWith("artifact_")) {
    const artifactId = (result.pdf_artifact_id ?? result.artifact_id) as string | undefined;
    if (artifactId) {
      return {
        artifactId,
        revisionId: (result.revision_id as string | undefined) ?? undefined,
      };
    }
  }
  if (["read_file", "write_file"].includes(call.capability)) {
    const path = call.args.path as string | undefined;
    if (path) return { path };
  }
  return null;
}

export interface FileRef {
  source: PreviewSource;
  name: string;
  /** true = the run created/modified the file; false = it only consulted it. */
  produced: boolean;
}

const FILE_ARTIFACT_PRODUCERS = new Set([
  "artifact_create",
  "artifact_revise",
  "artifact_restore",
]);
/**
 * Collect the output files a set of completed tool calls produced — chips
 * tag only files the run created/modified, never inputs it merely read
 * (the user's own attachments are inputs, shown on their message card).
 * Deduped by path/artifact; for artifacts the latest produced revision wins.
 */
export function collectFileRefs(calls: ToolCallData[]): FileRef[] {
  const seen = new Map<string, FileRef>();
  const base = (p: string) => p.split("/").pop() || p;
  const add = (key: string, ref: FileRef) => {
    const prev = seen.get(key);
    if (!prev || ref.produced) seen.set(key, ref);
  };
  for (const call of calls) {
    if (call.status !== "complete") continue;
    const result = (call.result ?? {}) as Record<string, unknown>;
    if (typeof result.error === "string") continue;

    if (call.capability === "write_file") {
      const path = (result.path ?? call.args.path) as string | undefined;
      if (path && result.action !== "unchanged") {
        add(`p:${path}`, { source: { path }, name: base(path), produced: true });
      }
    } else if (call.capability === "artifact_export_pdf") {
      const id = result.pdf_artifact_id as string | undefined;
      const path = result.pdf_path as string | undefined;
      if (id) {
        add(`a:${id}`, {
          source: { artifactId: id },
          name: path ? base(path) : "PDF export",
          produced: true,
        });
      }
    } else if (FILE_ARTIFACT_PRODUCERS.has(call.capability)) {
      const id = (result.artifact_id ?? call.args.artifact_id) as string | undefined;
      if (!id) continue;
      const path = result.path as string | undefined;
      add(`a:${id}`, {
        source: {
          artifactId: id,
          revisionId: (result.revision_id as string | undefined) ?? undefined,
        },
        name: path ? base(path) : "artifact",
        produced: true,
      });
    }
  }
  return [...seen.values()];
}

/** Chips row of output files a run produced — click opens the preview. */
export function FileChips({
  refs,
  onPreview,
}: {
  refs: FileRef[];
  onPreview?: (source: PreviewSource) => void;
}) {
  if (!onPreview || refs.length === 0) return null;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      <span className="mr-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--ink-3)]">
        files
      </span>
      {refs.map((ref, i) => (
        <button
          key={i}
          onClick={() => onPreview(ref.source)}
          title={`${ref.source.path ?? ref.name} — click to preview`}
          className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)]/60 py-0.5 pl-2 pr-2.5 text-[11px] text-[var(--ink-2)] transition-colors hover:border-[var(--accent)]/50 hover:bg-[var(--surface)] hover:text-[var(--ink)]"
          style={{ cursor: "pointer" }}
        >
          <FileText
            className="h-3 w-3 shrink-0"
            style={{ color: "var(--accent)" }}
          />
          <span className="max-w-[200px] truncate">{ref.name}</span>
        </button>
      ))}
    </div>
  );
}

const TERMINAL_CAPS = new Set(["terminal", "read_terminal", "close_terminal"]);

const TERMINAL_STATUS_COLORS: Record<string, string> = {
  running: "var(--warning)",
  completed: "var(--success)",
  failed: "var(--danger)",
  timeout: "var(--danger)",
  closed: "var(--ink-3)",
  interrupted: "var(--warning)",
};

function TerminalResult({ result }: { result: Record<string, unknown> }) {
  const status = typeof result.status === "string" ? result.status : "completed";
  const stdout = (result.stdout ?? result.stdout_tail ?? "") as string;
  const stderr = (result.stderr ?? result.stderr_tail ?? "") as string;
  const exitCode = result.exit_code as number | null | undefined;
  const terminalId = result.terminal_id as string | undefined;

  return (
    <div
      className="mb-2 overflow-x-auto rounded-[5px] p-2 font-mono text-[11px]"
      style={{ background: "var(--white)", border: "1px solid var(--border)", color: "var(--ink-2)" }}
    >
      <div className="flex items-center gap-2">
        <span style={{ color: TERMINAL_STATUS_COLORS[status] ?? "var(--ink-2)" }}>{status}</span>
        {exitCode != null && <span className="text-[var(--ink-3)]">exit {exitCode}</span>}
        {terminalId && <span className="text-[var(--ink-3)]">id {terminalId.slice(0, 8)}</span>}
        {result.truncated === true && <span className="text-[var(--warning)]">truncated</span>}
      </div>
      {stdout && <pre className="mt-1 whitespace-pre-wrap break-words text-[var(--ink-1)]">{stdout}</pre>}
      {stderr && <pre className="mt-1 whitespace-pre-wrap break-words text-[var(--danger)]">{stderr}</pre>}
    </div>
  );
}

export function ToolCallBlock({ call, subagentStream, onPreview }: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const [subExpanded, setSubExpanded] = useState(false);
  const [remember, setRemember] = useState(false);
  const [rememberScope, setRememberScope] = useState<"exact" | "same_verb" | "pattern" | "capability">("exact");
  const [rememberPattern, setRememberPattern] = useState("");
  const [approvalState, setApprovalState] = useState<
    "pending" | "approved" | "rejected" | "error"
  >(call.status === "pending_approval" ? "pending" : "pending");

  const statusConfig = {
    pending: { symbol: "⋯", color: "var(--ink-3)", label: "waiting" },
    pending_approval: { symbol: "⏸", color: "var(--warning)", label: "approval" },
    pending_input: { symbol: "?", color: "var(--info, var(--warning))", label: "asking" },
    running: { symbol: "⋯", color: "var(--warning)", label: "run" },
    complete: { symbol: "✓", color: "var(--success)", label: "done" },
    denied: { symbol: "✕", color: "var(--danger)", label: "denied" },
    failed: { symbol: "✕", color: "var(--danger)", label: "error" },
    timeout: { symbol: "⏱", color: "var(--warning)", label: "timeout" },
    interrupted: { symbol: "◼", color: "var(--warning)", label: "stopped" },
  };

  const config = statusConfig[call.status];
  const { label, detail } = describeCall(call.capability, call.args);
  const hasResult =
    call.status === "complete" && call.result != null ||
    call.status === "denied" ||
    call.status === "failed" ||
    call.status === "timeout" ||
    call.status === "interrupted";

  const isSubagent = call.capability === "run_subagent";

  const handleApprove = async () => {
    if (!call.approval_id) return;
    try {
      await api.approveCall(call.approval_id, remember, rememberScope, rememberPattern || undefined);
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
          <span className="text-[11px] font-medium text-[var(--ink-1)]">{label}</span>
          {detail && (
            <span className="min-w-0 truncate font-mono text-[11px] text-[var(--ink-3)]">{detail}</span>
          )}
          {onPreview && previewSourceFor(call) && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                const src = previewSourceFor(call);
                if (src) onPreview(src);
              }}
              title="Preview this file"
              aria-label="Preview this file"
              className="ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-[3px] text-[var(--ink-3)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--accent)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
          )}
          <span
            className={`ml-auto font-mono text-[11px] ${call.status === "running" ? "pulse" : ""}`}
            style={{ color: config.color }}
          >
            {config.symbol}
          </span>
        </div>
      )}

      {/* Raw signature — full audit detail one click away */}
      {expanded && (
        <div className="mb-1 truncate font-mono text-[10px] text-[var(--ink-3)]">
          {`${call.capability}(${formatArgs(call.capability, call.args)})`}
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
              {approvalState === "approved" && (
                call.approval_batch_size && call.approval_batch_size > 1
                  ? "Approved — waiting for the action batch"
                  : "Approved — executing..."
              )}
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
          {call.approval_batch_size && call.approval_batch_size > 1 && (
            <div className="mt-1.5 font-mono text-[10px] text-[var(--ink-3)]">
              This action has {call.approval_batch_size} approval requests. Nothing runs until all are decided.
            </div>
          )}
          {approvalState === "pending" && (
            <div className="mt-1.5">
              <label className="flex items-center gap-1.5 font-mono text-[10px] text-[var(--ink-3)]"
                style={{ cursor: "pointer", userSelect: "none" }}
              >
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => {
                    setRemember(e.target.checked);
                    if (!e.target.checked) setRememberScope("exact");
                  }}
                  style={{ cursor: "pointer" }}
                />
                Remember for this session
              </label>
              {remember && (
                <>
                  <select
                    value={rememberScope}
                    onChange={(e) => setRememberScope(e.target.value as "exact" | "same_verb" | "pattern" | "capability")}
                    className="mt-1 rounded-[4px] border px-1.5 py-0.5 font-mono text-[10px]"
                    style={{
                      borderColor: "var(--border)",
                      background: "var(--white)",
                      color: "var(--ink-2)",
                      cursor: "pointer",
                    }}
                  >
                    <option value="exact">This exact call only</option>
                    {call.capability === "terminal" && (
                      <option value="same_verb">All "{(call.args?.command as string || "").trim().split(/\s+/)[0] || "cmd"}" commands</option>
                    )}
                    <option value="pattern">Custom pattern (wildcard)</option>
                    <option value="capability">All {call.capability} calls</option>
                  </select>
                  {rememberScope === "pattern" && (
                    <input
                      type="text"
                      value={rememberPattern}
                      onChange={(e) => setRememberPattern(e.target.value)}
                      placeholder={
                        call.capability === "terminal"
                          ? `${(call.args?.command as string || "").trim().split(/\s+/)[0] || "cmd"} *`
                          : "*"
                      }
                      className="mt-1 w-full rounded-[4px] border px-1.5 py-0.5 font-mono text-[10px]"
                      style={{
                        borderColor: "var(--border)",
                        background: "var(--white)",
                        color: "var(--ink-2)",
                      }}
                    />
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Elicitation — waiting for user input (the chat bar handles the actual input) */}
      {call.status === "pending_input" && Boolean(call.elicitation_id) && (
        <div className="mb-2 rounded-[5px] border p-2.5"
          style={{ borderColor: "var(--warning)", background: "var(--surface)" }}
        >
          <div className="font-mono text-[11px] text-[var(--ink-2)]">
            Waiting for your input in the chat bar below…
          </div>
        </div>
      )}

      {/* Diff block for write_file results */}
      {call.status === "complete" && call.capability === "write_file" && Boolean(call.result) &&
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
      {expanded && hasResult && call.status === "complete" &&
        TERMINAL_CAPS.has(call.capability) &&
        typeof call.result === "object" && call.result !== null && (
        <TerminalResult result={call.result as Record<string, unknown>} />
      )}

      {expanded && hasResult &&
        !(call.capability === "write_file" && call.status === "complete" && typeof call.result === "object" && call.result !== null && "action" in (call.result as Record<string, unknown>)) &&
        !(call.status === "complete" && TERMINAL_CAPS.has(call.capability) && typeof call.result === "object" && call.result !== null) &&
        !(isSubagent && subagentStream && (subagentStream.items.length > 0 || subagentStream.text)) && (
        <div
          className="mb-2 overflow-x-auto whitespace-pre-wrap break-words rounded-[5px] p-2 font-mono text-[11px]"
          style={{
            background: "var(--white)",
            border: "1px solid var(--border)",
            color:
              call.status === "denied" || call.status === "failed"
                ? "var(--danger)"
                : "var(--ink-2)",
          }}
        >
          {call.status === "denied" || call.status === "failed" || call.status === "timeout" || call.status === "interrupted"
            ? typeof call.result === "string"
              ? call.result
              : call.status === "denied"
                ? "Call was denied by the syscall layer."
                : call.status === "timeout"
                  ? "Call timed out."
                  : call.status === "interrupted"
                    ? "Call was interrupted."
                    : "Call failed."
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
                if (item.type === "text") {
                  const text = item.data as { content: string };
                  return <div key={item.id} className="whitespace-pre-wrap text-[12px] text-[var(--ink-1)]">{text.content}</div>;
                }
                return <ToolCallBlock key={item.id} call={item.data as ToolCallData} />;
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

/** Verb-first label + the one argument a user actually wants to glance at. */
function describeCall(
  capability: string,
  args: Record<string, unknown>,
): { label: string; detail?: string } {
  const a = args;
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);
  const short = (v: unknown) => (typeof v === "string" ? v.slice(0, 8) : undefined);
  const trunc = (v: unknown, n = 80) => {
    const s = str(v);
    return s ? (s.length > n ? s.slice(0, n) + "…" : s) : undefined;
  };

  switch (capability) {
    case "terminal":
      return { label: "Run command", detail: trunc(a.command) };
    case "read_terminal":
      return { label: "Read terminal output", detail: short(a.terminal_id) };
    case "close_terminal":
      return { label: "Close terminal", detail: short(a.terminal_id) };
    case "read_file":
      return { label: "Read file", detail: trunc(a.path) };
    case "write_file":
      return { label: "Write file", detail: trunc(a.path) };
    case "search_files":
      return { label: "Search files", detail: trunc(a.pattern ?? a.query ?? a.path) };
    case "web_search":
      return { label: "Search the web", detail: trunc(a.query) };
    case "web_fetch":
      return { label: "Fetch page", detail: trunc(a.url) };
    case "datetime_now":
      return { label: "Check the time" };
    case "agent_ask_user":
      return { label: "Ask a question", detail: trunc(a.question) };
    case "run_subagent":
      return { label: "Delegate to sub-agent", detail: trunc(a.task, 60) };
    case "read_subagent":
      return { label: "Check sub-agent", detail: short(a.subagent_id ?? a.id) };
    case "memory_recall":
      return { label: "Recall memory", detail: trunc(a.query) };
    case "memory_store":
      return { label: "Store memory" };
    case "memory_remember_fact":
      return { label: "Remember a fact" };
    case "memory_query_facts":
      return { label: "Query memory" };
    case "memory_update":
      return { label: "Update memory" };
    case "skills_list":
      return { label: "List skills" };
    case "skills_load":
      return { label: "Load skill", detail: trunc(a.name ?? a.skill) };
    case "skills_read_resource":
      return { label: "Read skill resource", detail: trunc(a.path ?? a.resource) };
    case "capabilities_search":
      return { label: "Find a tool", detail: trunc(a.query) };
    case "capabilities_load":
      return { label: "Load tool", detail: trunc(JSON.stringify(a.names ?? a.capabilities ?? "")) };
    case "doc_search":
      return { label: "Search documents", detail: trunc(a.query) };
    case "doc_list":
      return { label: "List documents" };
    case "doc_inspect":
      return { label: "Inspect document", detail: trunc(a.doc_id ?? a.id ?? a.path) };
    case "search_history":
      return { label: "Search history", detail: trunc(a.query) };
    default: {
      // MCP tools and anything unregistered: humanize the name.
      const words = capability.replace(/^mcp[._]/, "").replace(/[._-]+/g, " ").trim();
      const label = words.charAt(0).toUpperCase() + words.slice(1);
      const firstArg = Object.values(a).find((v) => typeof v === "string" && v.length > 0);
      return { label, detail: trunc(firstArg) };
    }
  }
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
  return JSON.stringify(result, null, 2) ?? "";
}
