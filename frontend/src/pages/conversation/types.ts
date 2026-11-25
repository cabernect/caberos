import type { Message } from "@/lib/types";
import type { ToolCallData } from "@/components/ToolCallBlock";

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  run_id?: string;
  run_status?: string;
  trigger?: string;
  is_test?: boolean;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  subagent_id?: string | null;
  attachments?: string | null;
  citations?: Message["citations"];
}

export const mapApiMessage = (m: Message): ChatMessage => ({
  id: m.id,
  role: m.role,
  content: m.content,
  created_at: m.created_at,
  run_id: m.run_id,
  run_status: m.run_status,
  trigger: m.trigger,
  is_test: m.is_test,
  tokens_in: m.tokens_in,
  tokens_out: m.tokens_out,
  cost: m.cost,
  subagent_id: m.subagent_id,
  attachments: m.attachments,
  citations: m.citations,
});

export interface TurnCost {
  turnNumber: number;
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

export interface ThinkingBlockData {
  content: string;
  durationSec: number | null;
}

export type StreamItem =
  | { type: "thinking"; id: string; data: ThinkingBlockData }
  | { type: "text"; id: string; data: { content: string } }
  | { type: "tool"; id: string; data: ToolCallData };

export interface SubAgentStream {
  thinking: string;
  items: StreamItem[];
  text: string;
  toolCalls: Map<string, ToolCallData>;
  thinkingStartTime: number | null;
  completed: boolean;
}

export interface StreamingResponse {
  thinking: string;          // current turn's thinking (accumulating)
  items: StreamItem[];       // ordered list of completed thinking blocks + tool calls
  text: string;
  awaitingModel: boolean;    // a model call is dispatched, nothing streamed back yet — the between-turns gap
  toolCalls: Map<string, ToolCallData>;
  thinkingStartTime: number | null;
  thinkingEndTime: number | null;
  turnCosts: TurnCost[];
  guardrailWarnings: string[];
  toolProgress: { name: string | null; argsChars: number } | null;  // model is streaming a tool call's arguments
  retryNotice: string | null;   // transient model-call failure being retried
  completed: boolean;  // true when run is done — hides cursor, keeps content visible
  subagents: Map<string, SubAgentStream>;  // subagent_id -> nested stream
}

export interface ElicitationOption {
  label: string;
  description: string;
}

export interface ActiveElicitation {
  id: string;
  question: string;
  options: ElicitationOption[] | null;
  multiSelect: boolean;
}

export function createStreamingResponse(): StreamingResponse {
  return {
    thinking: "",
    items: [],
    text: "",
    awaitingModel: false,
    toolCalls: new Map(),
    thinkingStartTime: Date.now(),
    thinkingEndTime: null,
    turnCosts: [],
    guardrailWarnings: [],
    toolProgress: null,
    retryNotice: null,
    completed: false,
    subagents: new Map(),
  };
}

// Per-session /compact outcome — a request always applies its result to the
// session that started it, never whichever session happens to be on screen.
export interface CompactStatus {
  state: "pending" | "succeeded" | "unchanged" | "failed";
  originalTokens?: number;
  compactedTokens?: number;
  maxContextTokens?: number;
  message?: string;
}

// /context outcome — the last completed run's recorded snapshot, labeled
// honestly as "as of last run" rather than a live estimate.
export interface ContextInfo {
  state: "loading" | "ready" | "empty" | "error";
  contextTokens?: number;
  maxContextTokens?: number;
  compacted?: boolean;
  breakdown?: { system_prompt?: number; conversation?: number; tools?: number };
  asOf?: string;
  message?: string;
}
