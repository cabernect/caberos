import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { ToolCallBlock, type ToolCallData, type SubAgentStreamData } from "@/components/ToolCallBlock";
import { ThinkingBlock } from "@/components/ThinkingBlock";
import type { PreviewSource } from "@/lib/api";
import { cn } from "@/lib/utils";

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
  onPreview?: (source: PreviewSource) => void;
  /** Agent letter for the tile anchoring the turn (W13 mockup). */
  agentInitial?: string;
}

/**
 * Collapsed assistant-turn disclosure: tile + "Worked through N steps".
 * Expands to the full ToolCallBlock list — richer than the mockup's flat
 * step rows on purpose (approvals and previews live inside them).
 */
export function ProcessSteps({ steps, subagentMessages, onPreview, agentInitial }: ProcessStepsProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0) return null;

  const thinkingCount = steps.filter((s) => s.type === "thinking").length;
  const toolCount = steps.filter((s) => s.type === "tool_call").length;
  const summary =
    toolCount > 0
      ? `Worked through ${toolCount} step${toolCount !== 1 ? "s" : ""}${thinkingCount > 0 ? ` · ${thinkingCount} thinking` : ""}`
      : `${thinkingCount} thinking`;

  return (
    <div className="mb-4 flex gap-3">
      {agentInitial && (
        <span className="flex h-6 w-6 shrink-0 select-none items-center justify-center rounded-[8px] bg-accent-tint text-[12px] font-semibold text-accent">
          {agentInitial}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex cursor-pointer items-center gap-1.5 bg-none p-0"
          style={{ border: "none" }}
        >
          <Wrench className="h-3.5 w-3.5 text-ink-faint" />
          <span className="text-[13px] text-ink-muted transition-colors hover:text-ink">
            {summary}
          </span>
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 text-ink-faint transition-transform duration-150",
              expanded && "rotate-90",
            )}
          />
        </button>

        {expanded && (
          <div className="mt-2 space-y-1 border-l-2 border-line pl-3">
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
              try {
                const data = JSON.parse(step.content) as ToolCallData;
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
                    onPreview={onPreview}
                  />
                );
              } catch {
                return null;
              }
            })}
          </div>
        )}
      </div>
    </div>
  );
}
