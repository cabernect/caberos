import { useState } from "react";
import { ToolCallBlock, type ToolCallData, type SubAgentStreamData } from "@/components/ToolCallBlock";
import { ThinkingBlock } from "@/components/ThinkingBlock";

interface ThinkingBlockData {
  content: string;
  durationSec: number | null;
}

interface ProcessStep {
  type: "thinking" | "tool_call";
  content: string;
}

interface ProcessStepsProps {
  steps: ProcessStep[];
  subagentMessages?: { id: string; role: string; content: string }[];
}

export function ProcessSteps({ steps, subagentMessages }: ProcessStepsProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  // Count step types for the summary
  const thinkingCount = steps.filter((s) => s.type === "thinking").length;
  const toolCount = steps.filter((s) => s.type === "tool_call").length;

  // Build summary label
  const parts: string[] = [];
  if (thinkingCount > 0) parts.push(`${thinkingCount} thinking`);
  if (toolCount > 0) parts.push(`${toolCount} tool call${toolCount !== 1 ? "s" : ""}`);
  const summary = parts.join(" · ");

  return (
    <div className="mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 bg-none p-0"
        style={{ border: "none", cursor: "pointer" }}
      >
        <span
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: "var(--ink-3)" }}
        />
        <span className="font-mono text-[11px] text-[var(--ink-3)] transition hover:text-[var(--ink-2)]">
          {summary}
        </span>
        <span className="font-mono text-[11px] text-[var(--ink-3)]">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1 border-l-2 pl-3" style={{ borderColor: "var(--border)" }}>
          {steps.map((step, i) => {
            if (step.type === "thinking") {
              return (
                <ThinkingBlock
                  key={i}
                  content={step.content}
                  isStreaming={false}
                />
              );
            }
            // tool_call
            try {
              const data = JSON.parse(step.content) as ToolCallData;
              // Build subagent stream from persisted sub-agent messages
              let subagentStream: SubAgentStreamData | undefined;
              if (data.capability === "run_subagent" && subagentMessages && subagentMessages.length > 0) {
                const items: { type: "thinking" | "tool"; id: string; data: ThinkingBlockData | ToolCallData }[] = [];
                let text = "";
                for (const sm of subagentMessages) {
                  if (sm.role === "thinking") {
                    items.push({ type: "thinking", id: sm.id, data: { content: sm.content, durationSec: null } });
                  } else if (sm.role === "tool_call") {
                    try {
                      const tcData = JSON.parse(sm.content) as ToolCallData;
                      items.push({ type: "tool", id: sm.id, data: tcData });
                    } catch { /* skip */ }
                  } else if (sm.role === "assistant") {
                    text += sm.content;
                  }
                }
                subagentStream = { thinking: "", items, text, completed: true };
              }
              return (
                <ToolCallBlock
                  key={i}
                  call={data}
                  subagentStream={subagentStream}
                />
              );
            } catch {
              return null;
            }
          })}
        </div>
      )}
    </div>
  );
}
